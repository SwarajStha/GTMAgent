"""Understanding-layer orchestration (G11).

Ties the extractor + validator together and persists the result on the tender:

    raw text (title + description + dossier)  ->  FieldExtractor.extract_tender
        ->  ExtractionValidator.validate_tender (repair in place)
        ->  tenders.tender_profile  (JSON: the profile fields + a `_meta` block)

This is an explicit, opt-in step (an endpoint, an agent tool, or a scheduled
sweep) — NOT run inside `MatchingPipeline.run`, so matching stays cheap and
deterministic and an LLM call happens at most once per tender. The matcher reads
the stored `required_certifications` to drive the cert gate (G12); when no
profile has been stored it keeps its column-only behaviour.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Document, Tender
from app.understanding.extractor import FieldExtractor
from app.understanding.schemas import TenderProfile
from app.understanding.validator import ExtractionValidator

_DOSSIER_TEXT_CHARS = 4000

# Key under which extraction provenance is stored inside `tenders.tender_profile`.
META_KEY = "_meta"


def build_tender_text(session: Session, tender: Tender) -> str:
    """Concatenate the human-readable tender text for the extractor: title +
    procurement description (BT-24) + the first chunk of dossier text, if any."""
    parts: list[str] = []
    if tender.title:
        parts.append(str(tender.title))
    if tender.description:
        parts.append(str(tender.description))
    if tender.cpv_codes:
        parts.append("CPV: " + ", ".join(str(c) for c in tender.cpv_codes))
    doc_text = session.scalar(
        sa.select(Document.extracted_text)
        .where(Document.tender_id == tender.id)
        .where(Document.extracted_text.is_not(None))
        .limit(1)
    )
    if doc_text:
        parts.append(str(doc_text)[:_DOSSIER_TEXT_CHARS])
    return "\n\n".join(parts).strip()


def _tender_base(tender: Tender) -> dict[str, Any]:
    """Trustworthy structured columns the extractor must not overwrite."""
    return {
        "cpv_codes": [str(c) for c in (tender.cpv_codes or [])],
        "title": tender.title,
        "buyer_name": tender.buyer_name,
        "buyer_country": tender.buyer_country,
        "budget_eur": tender.budget_eur,
        "deadline": tender.deadline.date() if isinstance(tender.deadline, datetime) else None,
    }


def profile_to_storage(
    profile: TenderProfile, *, source: str, model: str, ok: bool, issues: list[str]
) -> dict[str, Any]:
    """Shape the JSON written to `tenders.tender_profile` — the flat profile
    fields plus a `_meta` provenance block."""
    payload = profile.model_dump(mode="json")
    payload[META_KEY] = {
        "source": source,  # "claude" | "fallback"
        "model": model,
        "validation_ok": ok,
        "issues": issues,
        "extracted_at": datetime.now(UTC).isoformat(),
    }
    return payload


def extract_and_store_tender_profile(
    session: Session,
    tender: Tender,
    extractor: FieldExtractor | None = None,
    validator: ExtractionValidator | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Extract → validate/repair → persist on `tender.tender_profile`.

    Returns the stored JSON dict. `extractor` is injectable so tests pass a fake
    Anthropic client (or rely on the offline fallback)."""
    extractor = extractor or FieldExtractor()
    validator = validator or ExtractionValidator()

    raw_text = build_tender_text(session, tender)
    profile = extractor.extract_tender(raw_text, base=_tender_base(tender))
    ok, issues = validator.validate_tender(profile, raw_text)

    # Whether the LLM actually contributed: a fallback profile has no enriched
    # soft fields. We infer the source from the presence of LLM-only content.
    used_llm = bool(
        profile.summary or profile.required_certifications or profile.keywords
    )
    source = "claude" if used_llm else "fallback"

    stored = profile_to_storage(
        profile, source=source, model=extractor.model, ok=ok, issues=issues
    )
    tender.tender_profile = stored
    session.add(tender)
    if commit:
        session.commit()
    return stored
