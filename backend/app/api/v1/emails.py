"""Outreach email generation endpoints."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import CompanyProfile, Document, Email, Match, Tender

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


def _document_label(document: Document) -> str:
    """Best-effort display name for an evidence snippet's source file.

    The `Document` model has no `filename` column; derive a human-readable
    label from the stored file path (preferred) or the source URL.
    """
    if document.storage_path:
        return document.storage_path.replace("\\", "/").rsplit("/", 1)[-1]
    tail = document.source_url.split("?")[0].split("#")[0].rstrip("/").rsplit("/", 1)[-1]
    return tail or document.source_url


def _document_snippets(documents: Sequence[Document]) -> list[dict[str, str]]:
    snippets: list[dict[str, str]] = []
    for document in documents:
        text = (document.extracted_text or "").strip()
        if not text:
            continue
        snippets.append(
            {
                "document_id": str(document.id),
                "filename": _document_label(document),
                "snippet": text[:500],
            }
        )
    return snippets


def _collect_evidence(
    match: Match,
    tender: Tender,
    company: CompanyProfile,
    documents: Sequence[Document],
) -> dict[str, Any]:
    return {
        "match_id": str(match.id),
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
        "company": {
            "id": str(company.id),
            "name": company.name,
            "country": company.country,
            "website": company.website,
            "capabilities": company.capabilities,
            "certifications": company.certifications,
        },
        "score_breakdown": {
            "semantic_score": match.semantic_score,
            "budget_score": match.budget_score,
            "location_score": match.location_score,
            "qualification_score": match.qualification_score,
            "final_score": match.final_score,
        },
        "match_explanation": match.explanation,
        "document_snippets": _document_snippets(documents),
    }


def _draft_from_evidence(evidence: dict[str, Any]) -> dict[str, str]:
    tender = evidence["tender"]
    company = evidence["company"]
    score = evidence["score_breakdown"]["final_score"]
    title = tender["title"] or f"TED notice {tender['ted_notice_id']}"
    company_name = company["name"]
    buyer = tender["buyer_name"] or "the public buyer"
    deadline = tender["deadline"] or "the published deadline"
    explanation = evidence.get("match_explanation") or "The match score indicates a relevant fit."

    subject = f"{title} - opportunity for {company_name}"
    body = (
        f"Hi {company_name} team,\n\n"
        f"We found a public tender from {buyer}: {title}. "
        f"The current match score is {score:.0%}, based on the tender context and your company "
        "profile.\n\n"
        f"Why this looks relevant: {explanation}\n\n"
        f"The listed deadline is {deadline}. I can share the parsed tender profile and evidence "
        "table if this opportunity is relevant for your pipeline.\n\n"
        "Best,\nGTM Agent"
    )
    return {"subject": subject, "body": body}


@router.post("/{match_id}/generate")
def generate_email(
    match_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> EmailOut:
    """Generate and store a deterministic evidence-grounded draft for a match."""
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
    evidence = _collect_evidence(match, tender, company, documents)
    draft = _draft_from_evidence(evidence)

    email = Email(
        match_id=match.id,
        subject=draft["subject"],
        body=draft["body"],
        evidence=evidence,
        status="draft",
    )
    db.add(email)
    db.commit()
    db.refresh(email)

    return _email_out(email, tender, company)


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
