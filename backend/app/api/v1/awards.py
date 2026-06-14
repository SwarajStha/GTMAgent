"""Award notice query endpoints."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import Award, Company

router = APIRouter()


class AwardOut(BaseModel):
    """Award row with the resolved winner name when available."""

    id: int
    ted_notice_id: str
    cpv_code: str | None
    buyer_name: str | None
    buyer_country: str | None
    winner_raw_name: str
    winner_canonical_id: int | None
    winner_canonical_name: str | None
    contract_value_eur: float | None
    award_date: date | None
    n_offers_received: int | None
    ingested_at: datetime


class AwardDetailOut(AwardOut):
    """Single award response, including raw TED payload."""

    raw_json: dict[str, Any]


class AwardListOut(BaseModel):
    """Paged award list response."""

    items: list[AwardOut]
    total: int
    limit: int
    offset: int


def _award_out(award: Award, winner_canonical_name: str | None) -> AwardOut:
    return AwardOut(
        id=award.id,
        ted_notice_id=award.ted_notice_id,
        cpv_code=award.cpv_code,
        buyer_name=award.buyer_name,
        buyer_country=award.buyer_country,
        winner_raw_name=award.winner_raw_name,
        winner_canonical_id=award.winner_canonical_id,
        winner_canonical_name=winner_canonical_name,
        contract_value_eur=award.contract_value_eur,
        award_date=award.award_date,
        n_offers_received=award.n_offers_received,
        ingested_at=award.ingested_at,
    )


def _award_detail_out(award: Award, winner_canonical_name: str | None) -> AwardDetailOut:
    base = _award_out(award, winner_canonical_name).model_dump()
    return AwardDetailOut(**base, raw_json=award.raw_json)


def _apply_filters(
    stmt: sa.Select[tuple[Award, str | None]],
    *,
    q: str | None,
    cpv_code: str | None,
    buyer_country: str | None,
    winner_canonical_id: int | None,
    date_from: date | None,
    date_to: date | None,
) -> sa.Select[tuple[Award, str | None]]:
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            sa.or_(
                Award.ted_notice_id.ilike(like),
                Award.buyer_name.ilike(like),
                Award.winner_raw_name.ilike(like),
                Company.canonical_name.ilike(like),
            )
        )
    if cpv_code:
        stmt = stmt.where(Award.cpv_code == cpv_code.strip())
    if buyer_country:
        stmt = stmt.where(Award.buyer_country == buyer_country.strip().upper())
    if winner_canonical_id is not None:
        stmt = stmt.where(Award.winner_canonical_id == winner_canonical_id)
    if date_from is not None:
        stmt = stmt.where(Award.award_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Award.award_date <= date_to)
    return stmt


@router.get("/")
def list_awards(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(description="Search TED id, buyer, or winner")] = None,
    cpv_code: Annotated[str | None, Query(description="Exact primary CPV code")] = None,
    buyer_country: Annotated[str | None, Query(description="Buyer country code")] = None,
    winner_canonical_id: Annotated[int | None, Query(ge=1)] = None,
    date_from: Annotated[date | None, Query(description="Minimum award date")] = None,
    date_to: Annotated[date | None, Query(description="Maximum award date")] = None,
) -> AwardListOut:
    """Return historical TED award notices from the ingestion pipeline."""
    base = _apply_filters(
        sa.select(Award, Company.canonical_name)
        .select_from(Award)
        .outerjoin(Company, Award.winner_canonical_id == Company.id),
        q=q,
        cpv_code=cpv_code,
        buyer_country=buyer_country,
        winner_canonical_id=winner_canonical_id,
        date_from=date_from,
        date_to=date_to,
    )
    total = db.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(Award.award_date.desc().nulls_last(), Award.ingested_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return AwardListOut(
        items=[_award_out(award, winner_name) for award, winner_name in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{award_id}")
def get_award(award_id: int, db: Annotated[Session, Depends(get_db)]) -> AwardDetailOut:
    """Return one award by numeric id."""
    row = db.execute(
        sa.select(Award, Company.canonical_name)
        .select_from(Award)
        .outerjoin(Company, Award.winner_canonical_id == Company.id)
        .where(Award.id == award_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Award not found")

    award, winner_name = row
    return _award_detail_out(award, winner_name)
