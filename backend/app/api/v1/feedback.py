"""User feedback endpoints.

Captures thumbs up/down ratings on matches and email drafts. Each rating snapshots
the match's 10-feature vector (`feedback.features`) so it stays a durable training
sample. `POST /feedback/retrain` (G8) fits the LR on those `(features, rating)`
pairs and writes `model_params_feedback.json`, which the matching pipeline then
serves in preference to the v5 base model.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import Email, Feedback, Match
from app.matching.features import FEATURE_NAMES

router = APIRouter()


def _match_features(match: Match) -> dict[str, float] | None:
    """Snapshot the match's 10 v5 features, or None if any is unset (a legacy
    fixed-weight or disqualified match — not usable as a training sample)."""
    values = {name: getattr(match, name, None) for name in FEATURE_NAMES}
    if any(v is None for v in values.values()):
        return None
    return {name: float(v) for name, v in values.items()}


class FeedbackCreate(BaseModel):
    """Feedback payload for match and optional email ratings."""

    match_id: uuid.UUID
    email_id: uuid.UUID | None = None
    rating: int = Field(ge=-1, le=1, description="Use 1 for thumbs up, -1 for thumbs down")
    comment: str | None = None


class FeedbackOut(BaseModel):
    """Stored feedback event."""

    id: uuid.UUID
    match_id: uuid.UUID
    email_id: uuid.UUID | None
    rating: int
    comment: str | None
    created_at: datetime
    updated_at: datetime


def _feedback_out(feedback: Feedback) -> FeedbackOut:
    return FeedbackOut(
        id=feedback.id,
        match_id=feedback.match_id,
        email_id=feedback.email_id,
        rating=feedback.rating,
        comment=feedback.comment,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


@router.post("/")
def submit_feedback(
    payload: FeedbackCreate,
    db: Annotated[Session, Depends(get_db)],
) -> FeedbackOut:
    """Accept thumbs-up/down feedback for a match and optional email draft."""
    if payload.rating == 0:
        raise HTTPException(status_code=422, detail="Rating must be 1 or -1")

    match = db.get(Match, payload.match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")

    if payload.email_id is not None:
        email_match_id = db.scalar(
            sa.select(Email.match_id).where(Email.id == payload.email_id)
        )
        if email_match_id is None:
            raise HTTPException(status_code=404, detail="Email not found")
        if email_match_id != payload.match_id:
            raise HTTPException(
                status_code=400,
                detail="Email does not belong to the provided match",
            )

    feedback = Feedback(
        match_id=payload.match_id,
        email_id=payload.email_id,
        rating=payload.rating,
        comment=payload.comment,
        features=_match_features(match),  # durable training snapshot (Step 5)
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)

    return _feedback_out(feedback)


class RetrainResultOut(BaseModel):
    """Outcome of a feedback-driven LR retraining run."""

    status: str  # "retrained" | "insufficient"
    n_samples: int
    n_pos: int
    n_neg: int
    min_required: int | None = None
    out_path: str | None = None
    coefficients: dict[str, float] | None = None


@router.post("/retrain")
def retrain_weights(
    db: Annotated[Session, Depends(get_db)],
    min_samples: Annotated[int, Query(ge=2, le=10_000)] = 10,
) -> RetrainResultOut:
    """Retrain the matcher's LR weights from collected feedback (G8).

    On success writes `exports/model_params_feedback.json`, which the matching
    pipeline then serves in preference to the v5 base model (delete that file to
    revert). Refuses with ``status="insufficient"`` until enough feedback (both
    thumbs-up and thumbs-down) has accumulated.
    """
    from app.matching.lr_weights import FeedbackRetrainer

    result = FeedbackRetrainer(min_samples=min_samples).retrain(db)
    return RetrainResultOut(**result)
