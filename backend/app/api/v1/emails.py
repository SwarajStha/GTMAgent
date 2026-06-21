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
            # v5 LR features (NULL on legacy fixed-weight matches).
            "cpv_4digit_score": match.cpv_4digit_score,
            "cpv_2digit_score": match.cpv_2digit_score,
            "nuts_exact_score": match.nuts_exact_score,
            "nuts_country_score": match.nuts_country_score,
            "value_score": match.value_score,
            "value_in_range_score": match.value_in_range_score,
            "country_match_score": match.country_match_score,
            "company_size_score": match.company_size_score,
            "competition_score": match.competition_score,
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


def _draft_buyer_email(
    tender: Tender, ranked: list[tuple[Match, CompanyProfile]]
) -> dict[str, str]:
    """Buyer-facing draft: tell the tender issuer which suppliers fit best."""
    title = tender.title or f"TED notice {tender.ted_notice_id}"
    buyer = tender.buyer_name or "team"
    lines = [
        f"1. {company.name}"
        + (f" ({company.country})" if company.country else "")
        + f" — fit {match.final_score:.0%}"
        + (f"\n   {match.explanation}" if match.explanation else "")
        for match, company in ranked
    ]
    subject = f"Recommended suppliers for {title} ({tender.ted_notice_id})"
    body = (
        f"Hi {buyer},\n\n"
        f"We analysed the market for your tender '{title}' and identified "
        f"{len(ranked)} supplier(s) that strongly match its requirements:\n\n"
        + "\n".join(lines)
        + "\n\nThese rankings combine semantic fit, budget alignment, location, and "
        "qualifications. I'm happy to share the full evidence table for any of them.\n\n"
        "Best,\nGTM Agent"
    )
    return {"subject": subject, "body": body}


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
    draft = _draft_buyer_email(tender, ranked)
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
