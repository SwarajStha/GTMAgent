"""User feedback endpoints.

Captures thumbs up/down ratings on matches and email drafts. The feedback
loop feeds into the logistic-regression weight learner in Phase 5.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import Email, Feedback, Match

router = APIRouter()


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

    match_exists = db.scalar(sa.select(sa.exists().where(Match.id == payload.match_id)))
    if not match_exists:
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
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)

    return _feedback_out(feedback)
