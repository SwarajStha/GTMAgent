"""Match result endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import CompanyProfile, Email, Match, Tender

router = APIRouter()


class TenderSummaryOut(BaseModel):
    """Tender fields shown beside a match."""

    id: int
    ted_notice_id: str
    title: str | None
    buyer_name: str | None
    buyer_country: str | None
    deadline: datetime | None
    budget_eur: float | None
    status: str


class CompanyProfileSummaryOut(BaseModel):
    """Company profile fields shown beside a match."""

    id: uuid.UUID
    name: str
    country: str | None
    website: str | None


class EmailSummaryOut(BaseModel):
    """Stored draft summary linked to a match."""

    id: uuid.UUID
    subject: str
    status: str
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MatchOut(BaseModel):
    """Ranked match response with score breakdown and context."""

    id: uuid.UUID
    tender_id: int
    company_id: uuid.UUID
    semantic_score: float
    budget_score: float
    location_score: float
    qualification_score: float
    # v5 LR feature columns (NULL on legacy fixed-weight matches).
    cpv_4digit_score: float | None = None
    cpv_2digit_score: float | None = None
    nuts_exact_score: float | None = None
    nuts_country_score: float | None = None
    value_score: float | None = None
    value_in_range_score: float | None = None
    country_match_score: float | None = None
    company_size_score: float | None = None
    competition_score: float | None = None
    final_score: float
    weights: dict[str, Any] | None
    explanation: str | None
    is_disqualified: bool
    created_at: datetime
    updated_at: datetime
    tender: TenderSummaryOut
    company: CompanyProfileSummaryOut


class MatchDetailOut(MatchOut):
    """Single match response including generated email summaries."""

    emails: list[EmailSummaryOut]


class MatchListOut(BaseModel):
    """Paged match list response."""

    items: list[MatchOut]
    total: int
    limit: int
    offset: int


def _tender_summary(tender: Tender) -> TenderSummaryOut:
    return TenderSummaryOut(
        id=tender.id,
        ted_notice_id=tender.ted_notice_id,
        title=tender.title,
        buyer_name=tender.buyer_name,
        buyer_country=tender.buyer_country,
        deadline=tender.deadline,
        budget_eur=tender.budget_eur,
        status=tender.status,
    )


def _company_summary(company: CompanyProfile) -> CompanyProfileSummaryOut:
    return CompanyProfileSummaryOut(
        id=company.id,
        name=company.name,
        country=company.country,
        website=company.website,
    )


def _match_out(match: Match, tender: Tender, company: CompanyProfile) -> MatchOut:
    return MatchOut(
        id=match.id,
        tender_id=match.tender_id,
        company_id=match.company_id,
        semantic_score=match.semantic_score,
        budget_score=match.budget_score,
        location_score=match.location_score,
        qualification_score=match.qualification_score,
        cpv_4digit_score=match.cpv_4digit_score,
        cpv_2digit_score=match.cpv_2digit_score,
        nuts_exact_score=match.nuts_exact_score,
        nuts_country_score=match.nuts_country_score,
        value_score=match.value_score,
        value_in_range_score=match.value_in_range_score,
        country_match_score=match.country_match_score,
        company_size_score=match.company_size_score,
        competition_score=match.competition_score,
        final_score=match.final_score,
        weights=match.weights,
        explanation=match.explanation,
        is_disqualified=match.is_disqualified,
        created_at=match.created_at,
        updated_at=match.updated_at,
        tender=_tender_summary(tender),
        company=_company_summary(company),
    )


def _email_summary(email: Email) -> EmailSummaryOut:
    return EmailSummaryOut(
        id=email.id,
        subject=email.subject,
        status=email.status,
        sent_at=email.sent_at,
        created_at=email.created_at,
        updated_at=email.updated_at,
    )


def _apply_filters(
    stmt: sa.Select[tuple[Match, Tender, CompanyProfile]],
    *,
    tender_id: int | None,
    company_id: uuid.UUID | None,
    min_score: float | None,
    include_disqualified: bool,
) -> sa.Select[tuple[Match, Tender, CompanyProfile]]:
    if tender_id is not None:
        stmt = stmt.where(Match.tender_id == tender_id)
    if company_id is not None:
        stmt = stmt.where(Match.company_id == company_id)
    if min_score is not None:
        stmt = stmt.where(Match.final_score >= min_score)
    if not include_disqualified:
        stmt = stmt.where(Match.is_disqualified.is_(False))
    return stmt


@router.get("/")
def list_matches(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    tender_id: Annotated[int | None, Query(ge=1)] = None,
    company_id: uuid.UUID | None = None,
    min_score: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    include_disqualified: bool = False,
) -> MatchListOut:
    """Return ranked company-profile matches for active dashboard views."""
    base = _apply_filters(
        sa.select(Match, Tender, CompanyProfile)
        .select_from(Match)
        .join(Tender, Match.tender_id == Tender.id)
        .join(CompanyProfile, Match.company_id == CompanyProfile.id),
        tender_id=tender_id,
        company_id=company_id,
        min_score=min_score,
        include_disqualified=include_disqualified,
    )
    total = db.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(Match.final_score.desc(), Match.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return MatchListOut(
        items=[_match_out(match, tender, company) for match, tender, company in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{match_id}")
def get_match(
    match_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> MatchDetailOut:
    """Return one match with tender, company profile, and email summaries."""
    row = db.execute(
        sa.select(Match, Tender, CompanyProfile)
        .select_from(Match)
        .join(Tender, Match.tender_id == Tender.id)
        .join(CompanyProfile, Match.company_id == CompanyProfile.id)
        .where(Match.id == match_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Match not found")

    match, tender, company = row
    emails = db.scalars(
        sa.select(Email)
        .where(Email.match_id == match_id)
        .order_by(Email.created_at.desc())
    ).all()
    base = _match_out(match, tender, company).model_dump()
    return MatchDetailOut(**base, emails=[_email_summary(email) for email in emails])


class MatchRunResultOut(BaseModel):
    """Result of running the matching pipeline for one tender."""

    tender_id: int
    count: int
    mode: str  # "lr" (trained model) | "weighted" (operator weights)
    weights: dict[str, float] | None = None
    matches: list[dict[str, Any]]


class MatchWeightsIn(BaseModel):
    """Operator weights for the legacy four-factor combine (G16).

    Posting these re-ranks the tender in weighted mode instead of the trained LR,
    so the slider overrides in the UI become a persisted, server-side re-rank
    rather than ephemeral client state. Each weight is relative (the pipeline
    normalises by their sum); negatives are rejected."""

    semantic: float = Field(ge=0.0)
    budget: float = Field(ge=0.0)
    location: float = Field(ge=0.0)
    qualification: float = Field(ge=0.0)


@router.post("/run/{tender_id}")
def run_matching(
    tender_id: int,
    db: Annotated[Session, Depends(get_db)],
    top_n: Annotated[int | None, Query(ge=1, le=200)] = None,
    weights: MatchWeightsIn | None = None,
) -> MatchRunResultOut:
    """Rank the company-profile pool for a tender and persist `matches`.

    Runs synchronously: the first call loads MiniLM (~10s, then cached). Returns
    the ranked result; fetch full rows afterwards via `GET /matches?tender_id=`.

    Default (no body) uses the trained LR scorer. Posting a `weights` body
    re-ranks with the legacy four-factor weighted combine using those weights
    (G16) — the operator's slider overrides, persisted to `matches.weights`.
    """
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")

    # Imported here so the matching/ML stack is only pulled when matching runs.
    from app.matching.pipeline import MatchingPipeline

    if weights is not None:
        if sum(weights.model_dump().values()) <= 0:
            raise HTTPException(status_code=422, detail="weights must sum to a positive value")
        pipeline = MatchingPipeline(weights=weights.model_dump(), use_lr=False)
        mode = "weighted"
    else:
        pipeline = MatchingPipeline()
        # Honest reporting: the default path serves the trained LR only when the
        # model params loaded; otherwise it falls back to the fixed-weight combine.
        mode = "lr" if pipeline.lr_scorer is not None else "weighted"

    results = pipeline.run(tender_id, session=db, top_n=top_n)
    return MatchRunResultOut(
        tender_id=tender_id,
        count=len(results),
        mode=mode,
        weights=weights.model_dump() if weights is not None else None,
        matches=results,
    )
