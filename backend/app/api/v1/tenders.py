"""Tender list and detail endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import CompanyProfile, Match, Tender, TenderReport

router = APIRouter()


class TenderOut(BaseModel):
    """API shape consumed by the frontend tender workbench."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ted_notice_id: str
    title: str | None
    buyer_name: str | None
    buyer_country: str | None
    cpv_codes: list[str]
    deadline: datetime | None
    budget_eur: float | None
    currency: str | None
    status: str
    document_url: str | None
    is_restricted: bool
    ingested_at: datetime
    updated_at: datetime


class TenderDetailOut(TenderOut):
    """Single-tender response, including raw TED payload for inspection."""

    raw_json: dict[str, Any]
    tender_profile: dict[str, Any] | None = None


class TenderProfileOut(BaseModel):
    """Response of the Understanding-layer extraction endpoint."""

    tender_id: int
    profile: dict[str, Any]


class TenderListOut(BaseModel):
    """Paged tender list response."""

    items: list[TenderOut]
    total: int
    limit: int
    offset: int


def _apply_filters(
    stmt: sa.Select[tuple[Tender]],
    *,
    q: str | None,
    country: str | None,
    status: str | None,
    cpv: str | None,
) -> sa.Select[tuple[Tender]]:
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            sa.or_(
                Tender.title.ilike(like),
                Tender.buyer_name.ilike(like),
                Tender.ted_notice_id.ilike(like),
            )
        )
    if country:
        stmt = stmt.where(Tender.buyer_country == country.strip().upper())
    if status:
        stmt = stmt.where(Tender.status == status.strip())
    if cpv:
        stmt = stmt.where(Tender.cpv_codes.contains([cpv.strip()]))
    return stmt


@router.get("/")
def list_tenders(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(description="Search title, buyer, or TED id")] = None,
    country: Annotated[str | None, Query(description="Buyer country code")] = None,
    status: Annotated[str | None, Query(description="Tender status")] = None,
    cpv: Annotated[str | None, Query(description="Exact CPV code")] = None,
) -> TenderListOut:
    """Return tenders stored by the TED ingestion pipeline."""
    base = _apply_filters(sa.select(Tender), q=q, country=country, status=status, cpv=cpv)
    total = db.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Tender.deadline.asc().nulls_last(), Tender.ingested_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return TenderListOut(
        items=[TenderOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{tender_id}")
def get_tender(tender_id: str, db: Annotated[Session, Depends(get_db)]) -> TenderDetailOut:
    """Return one tender by numeric id or TED notice id."""
    stmt = sa.select(Tender)
    if tender_id.isdigit():
        stmt = stmt.where(Tender.id == int(tender_id))
    else:
        stmt = stmt.where(Tender.ted_notice_id == tender_id)

    tender = db.scalars(stmt).first()
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")

    return TenderDetailOut.model_validate(tender)


def _resolve_tender(db: Session, tender_id: str) -> Tender:
    stmt = sa.select(Tender)
    if tender_id.isdigit():
        stmt = stmt.where(Tender.id == int(tender_id))
    else:
        stmt = stmt.where(Tender.ted_notice_id == tender_id)
    tender = db.scalars(stmt).first()
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    return tender


@router.post("/{tender_id}/extract")
def extract_tender_profile(
    tender_id: str, db: Annotated[Session, Depends(get_db)]
) -> TenderProfileOut:
    """Run the Understanding layer (G11) on one tender and persist the structured
    `TenderProfile` to `tenders.tender_profile`.

    Uses Claude when `ANTHROPIC_API_KEY` is configured, else a deterministic
    fallback built from the tender's own columns — so it always returns a profile.
    The stored `required_certifications` subsequently drive the matcher's cert
    gate (G12). Safe to call repeatedly (re-extracts and overwrites)."""
    from app.understanding.service import extract_and_store_tender_profile

    tender = _resolve_tender(db, tender_id)
    stored = extract_and_store_tender_profile(db, tender)
    return TenderProfileOut(tender_id=tender.id, profile=stored)


# ── Saved agent analyses (tender_reports, migration 0015) ────────────────────

class TenderReportIn(BaseModel):
    """Request to save an agent analysis for a tender.

    The structured supplier snapshot is built server-side from the tender's
    current `matches` (authoritative), so the client only sends the narrative.
    """

    narrative: str
    goal: str | None = None
    session_id: uuid.UUID | None = None


class TenderReportOut(BaseModel):
    id: uuid.UUID
    tender_id: int
    session_id: uuid.UUID | None
    goal: str | None
    narrative: str
    suppliers: list[dict[str, Any]] | None
    created_at: datetime


def _report_out(report: TenderReport) -> TenderReportOut:
    return TenderReportOut(
        id=report.id,
        tender_id=report.tender_id,
        session_id=report.session_id,
        goal=report.goal,
        narrative=report.narrative,
        suppliers=report.suppliers,
        created_at=report.created_at,
    )


def _supplier_snapshot(db: Session, tender_id: int, top_n: int = 5) -> list[dict[str, Any]]:
    """Snapshot the tender's current top-N (non-disqualified) matches."""
    rows = db.execute(
        sa.select(Match, CompanyProfile)
        .join(CompanyProfile, Match.company_id == CompanyProfile.id)
        .where(Match.tender_id == tender_id)
        .where(Match.is_disqualified.is_(False))
        .order_by(Match.final_score.desc())
        .limit(max(1, top_n))
    ).tuples().all()
    return [
        {
            "match_id": str(match.id),
            "company_id": str(company.id),
            "company_name": company.name,
            "final_score": match.final_score,
            "semantic_score": match.semantic_score,
            "budget_score": match.budget_score,
            "location_score": match.location_score,
            "qualification_score": match.qualification_score,
        }
        for match, company in rows
    ]


@router.post("/{tender_id}/reports")
def save_tender_report(
    tender_id: str,
    payload: TenderReportIn,
    db: Annotated[Session, Depends(get_db)],
) -> TenderReportOut:
    """Persist an agent analysis (narrative + a snapshot of the current ranked
    matches) for a tender. History is kept — each call appends a new report."""
    tender = _resolve_tender(db, tender_id)
    report = TenderReport(
        tender_id=tender.id,
        session_id=payload.session_id,
        goal=payload.goal,
        narrative=payload.narrative,
        suppliers=_supplier_snapshot(db, tender.id),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return _report_out(report)


@router.get("/{tender_id}/reports")
def list_tender_reports(
    tender_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> list[TenderReportOut]:
    """List saved analyses for a tender, newest first."""
    tender = _resolve_tender(db, tender_id)
    reports = db.scalars(
        sa.select(TenderReport)
        .where(TenderReport.tender_id == tender.id)
        .order_by(TenderReport.created_at.desc())
    ).all()
    return [_report_out(r) for r in reports]
