"""Outreach email generation endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import CompanyProfile, Document, Email, Match, Tender
from app.generation.drafter import EmailDrafter
from app.generation.evidence import EvidenceExtractor

router = APIRouter()


class EmailTenderContextOut(BaseModel):
    """Tender context attached to a generated email."""

    id: int
    ted_notice_id: str
    title: str | None
    buyer_name: str | None
    buyer_country: str | None
    deadline: datetime | None
    budget_eur: float | None


class EmailCompanyContextOut(BaseModel):
    """Company profile context attached to a generated email."""

    id: uuid.UUID
    name: str
    country: str | None
    website: str | None


class EmailOut(BaseModel):
    """Stored outreach draft with match context."""

    id: uuid.UUID
    match_id: uuid.UUID
    recipient_type: str
    subject: str
    body: str
    evidence: dict[str, Any] | None
    status: str
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
    tender: EmailTenderContextOut
    company: EmailCompanyContextOut


def _tender_context(tender: Tender) -> EmailTenderContextOut:
    return EmailTenderContextOut(
        id=tender.id,
        ted_notice_id=tender.ted_notice_id,
        title=tender.title,
        buyer_name=tender.buyer_name,
        buyer_country=tender.buyer_country,
        deadline=tender.deadline,
        budget_eur=tender.budget_eur,
    )


def _company_context(company: CompanyProfile) -> EmailCompanyContextOut:
    return EmailCompanyContextOut(
        id=company.id,
        name=company.name,
        country=company.country,
        website=company.website,
    )


def _email_out(
    email: Email,
    tender: Tender,
    company: CompanyProfile,
) -> EmailOut:
    return EmailOut(
        id=email.id,
        match_id=email.match_id,
        recipient_type=email.recipient_type,
        subject=email.subject,
        body=email.body,
        evidence=email.evidence,
        status=email.status,
        sent_at=email.sent_at,
        created_at=email.created_at,
        updated_at=email.updated_at,
        tender=_tender_context(tender),
        company=_company_context(company),
    )


def _find_match_context(
    db: Session,
    match_id: uuid.UUID,
) -> tuple[Match, Tender, CompanyProfile] | None:
    return db.execute(
        sa.select(Match, Tender, CompanyProfile)
        .select_from(Match)
        .join(Tender, Match.tender_id == Tender.id)
        .join(CompanyProfile, Match.company_id == CompanyProfile.id)
        .where(Match.id == match_id)
    ).tuples().first()


@router.post("/{match_id}/generate")
def generate_email(
    match_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> EmailOut:
    """Generate and store an evidence-grounded supplier outreach draft for a match.

    Drafts via Claude (`EmailDrafter`) when an API key is configured, else a
    deterministic template. Either way the stored `evidence` captures the facts
    the draft was grounded in.
    """
    row = _find_match_context(db, match_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Match not found")

    match, tender, company = row
    documents = db.scalars(
        sa.select(Document)
        .where(Document.tender_id == tender.id)
        .order_by(Document.downloaded_at.desc().nulls_last())
        .limit(3)
    ).all()
    evidence = EvidenceExtractor.build(match, tender, company, documents)
    draft = EmailDrafter().draft(evidence, recipient_type="supplier")
    evidence["draft_generator"] = draft["generator"]

    email = Email(
        match_id=match.id,
        tender_id=tender.id,
        recipient_type="supplier",
        subject=draft["subject"],
        body=draft["body"],
        evidence=evidence,
        status="draft",
    )
    db.add(email)
    db.commit()
    db.refresh(email)

    return _email_out(email, tender, company)


@router.post("/buyer/{tender_id}/generate")
def generate_buyer_email(
    tender_id: int,
    db: Annotated[Session, Depends(get_db)],
    top_n: int = 3,
) -> EmailOut:
    """Generate a buyer-facing digest recommending a tender's top supplier matches."""
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")

    rows = db.execute(
        sa.select(Match, CompanyProfile)
        .select_from(Match)
        .join(CompanyProfile, Match.company_id == CompanyProfile.id)
        .where(Match.tender_id == tender_id)
        .where(Match.is_disqualified.is_(False))
        .order_by(Match.final_score.desc())
        .limit(max(1, top_n))
    ).tuples().all()
    if not rows:
        raise HTTPException(
            status_code=409,
            detail="No matches for this tender yet — run the matching pipeline first.",
        )

    ranked: list[tuple[Match, CompanyProfile]] = list(rows)
    anchor_match, anchor_company = ranked[0]
    evidence: dict[str, Any] = {
        "recipient_type": "buyer",
        "tender": {
            "id": tender.id,
            "ted_notice_id": tender.ted_notice_id,
            "title": tender.title,
            "buyer_name": tender.buyer_name,
            "buyer_country": tender.buyer_country,
            "deadline": tender.deadline.isoformat() if tender.deadline else None,
            "budget_eur": tender.budget_eur,
            "cpv_codes": tender.cpv_codes,
        },
        "recommended_suppliers": [
            {
                "company_id": str(company.id),
                "name": company.name,
                "country": company.country,
                "website": company.website,
                "final_score": match.final_score,
                "explanation": match.explanation,
            }
            for match, company in ranked
        ],
    }
    draft = EmailDrafter().draft(evidence, recipient_type="buyer")
    evidence["draft_generator"] = draft["generator"]

    email = Email(
        match_id=anchor_match.id,  # anchor to the top match (keeps match_id NOT NULL)
        tender_id=tender.id,
        recipient_type="buyer",
        subject=draft["subject"],
        body=draft["body"],
        evidence=evidence,
        status="draft",
    )
    db.add(email)
    db.commit()
    db.refresh(email)

    return _email_out(email, tender, anchor_company)


@router.get("/{email_id}")
def get_email(
    email_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> EmailOut:
    """Fetch a stored email draft by id."""
    row = db.execute(
        sa.select(Email, Tender, CompanyProfile)
        .select_from(Email)
        .join(Match, Email.match_id == Match.id)
        .join(Tender, Match.tender_id == Tender.id)
        .join(CompanyProfile, Match.company_id == CompanyProfile.id)
        .where(Email.id == email_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")

    email, tender, company = row
    return _email_out(email, tender, company)
