"""Tender list and detail endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import Tender

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
