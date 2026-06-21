"""Evidence extractor.

Builds the structured, factual evidence dict the drafter is constrained to cite
for a single (tender, company) match — tender context, company profile, score
breakdown, match explanation, and dossier snippets. Centralised here (G10) so
the `/emails` endpoint and the agent's `draft_email` tool produce identical
evidence; the drafter must only mention facts present in this dict.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import CompanyProfile, Document, Match, Tender


def _document_label(document: Document) -> str:
    """Best-effort display name for a snippet's source file.

    The `Document` model has no `filename` column; derive a human-readable label
    from the stored file path (preferred) or the source URL.
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


class EvidenceExtractor:
    """Collects the citable evidence dict for a single match."""

    @staticmethod
    def build(
        match: Match,
        tender: Tender,
        company: CompanyProfile,
        documents: Sequence[Document],
    ) -> dict[str, Any]:
        """Assemble the evidence dict from already-loaded ORM objects."""
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

    def collect(
        self,
        session: Session,
        match_id: uuid.UUID | str,
        document_limit: int = 3,
    ) -> dict[str, Any] | None:
        """Fetch a match (with tender, company, dossiers) and build its evidence.

        Returns None if the match does not exist. Used by the agent's
        `draft_email` tool, which only has a match id to start from.
        """
        mid = match_id if isinstance(match_id, uuid.UUID) else uuid.UUID(str(match_id))
        row = session.execute(
            sa.select(Match, Tender, CompanyProfile)
            .select_from(Match)
            .join(Tender, Match.tender_id == Tender.id)
            .join(CompanyProfile, Match.company_id == CompanyProfile.id)
            .where(Match.id == mid)
        ).tuples().first()
        if row is None:
            return None
        match, tender, company = row
        documents = session.scalars(
            sa.select(Document)
            .where(Document.tender_id == tender.id)
            .order_by(Document.downloaded_at.desc().nulls_last())
            .limit(document_limit)
        ).all()
        return self.build(match, tender, company, documents)
