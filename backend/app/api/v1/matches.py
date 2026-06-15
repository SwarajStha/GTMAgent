"""Match result endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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
