"""Canonical award-winner company query endpoints."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.awards import AwardOut, _award_out
from app.db.models import Award, Company

router = APIRouter()


class CompanyOut(BaseModel):
    """Canonical company plus award-history rollups."""

    id: int
    canonical_name: str
    resolution_key: str
    aliases: list[str]
    country: str | None
    created_at: datetime
    award_count: int
    total_contract_value_eur: float | None
    latest_award_date: date | None


class CompanyDetailOut(CompanyOut):
    """Single company response with recent awards."""

    recent_awards: list[AwardOut]


class CompanyListOut(BaseModel):
    """Paged company list response."""

    items: list[CompanyOut]
    total: int
    limit: int
    offset: int


def _company_out(
    company: Company,
    award_count: int | None,
    total_contract_value_eur: float | None,
    latest_award_date: date | None,
) -> CompanyOut:
    return CompanyOut(
        id=company.id,
        canonical_name=company.canonical_name,
        resolution_key=company.resolution_key,
        aliases=company.aliases,
        country=company.country,
        created_at=company.created_at,
        award_count=award_count or 0,
        total_contract_value_eur=total_contract_value_eur,
        latest_award_date=latest_award_date,
    )


def _company_select() -> sa.Select[tuple[Company, int, float | None, date | None]]:
    return (
        sa.select(
            Company,
            sa.func.count(Award.id).label("award_count"),
            sa.func.sum(Award.contract_value_eur).label("total_contract_value_eur"),
            sa.func.max(Award.award_date).label("latest_award_date"),
        )
        .select_from(Company)
        .outerjoin(Award, Award.winner_canonical_id == Company.id)
        .group_by(Company.id)
    )


def _apply_filters(
    stmt: sa.Select[tuple[Company, int, float | None, date | None]],
    *,
    q: str | None,
    country: str | None,
) -> sa.Select[tuple[Company, int, float | None, date | None]]:
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            sa.or_(
                Company.canonical_name.ilike(like),
                Company.resolution_key.ilike(like),
            )
        )
    if country:
        stmt = stmt.where(Company.country == country.strip().upper())
    return stmt


@router.get("/")
def list_companies(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(description="Search canonical name")] = None,
    country: Annotated[str | None, Query(description="Company country code")] = None,
) -> CompanyListOut:
    """Return canonical companies resolved from award winners."""
    base = _apply_filters(_company_select(), q=q, country=country)
    total = db.scalar(
        sa.select(sa.func.count()).select_from(
            _apply_filters(sa.select(Company), q=q, country=country).subquery()
        )
    ) or 0
    rows = db.execute(
        base.order_by(sa.desc("award_count"), Company.canonical_name.asc())
        .offset(offset)
        .limit(limit)
    ).all()

    return CompanyListOut(
        items=[
            _company_out(company, award_count, total_value, latest_date)
            for company, award_count, total_value, latest_date in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{company_id}")
def get_company(company_id: int, db: Annotated[Session, Depends(get_db)]) -> CompanyDetailOut:
    """Return one canonical company with recent award history."""
    row = db.execute(_company_select().where(Company.id == company_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")

    company, award_count, total_value, latest_date = row
    awards = db.execute(
        sa.select(Award, Company.canonical_name)
        .select_from(Award)
        .join(Company, Award.winner_canonical_id == Company.id)
        .where(Award.winner_canonical_id == company_id)
        .order_by(Award.award_date.desc().nulls_last(), Award.ingested_at.desc())
        .limit(25)
    ).all()

    base = _company_out(company, award_count, total_value, latest_date).model_dump()
    return CompanyDetailOut(
        **base,
        recent_awards=[_award_out(award, winner_name) for award, winner_name in awards],
    )
