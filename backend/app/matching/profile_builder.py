"""Layer 1 — build the supplier pool (`company_profiles`) from award winners.

The matcher ranks `company_profiles` (which carry capability text + an
embedding) per tender. Those profiles are *derived* from the minimal
award-winner `companies` rows (Job 2) plus that company's `awards` history —
CLAUDE.md keeps the two tables separate (entities vs. matchable profiles), so we
populate one from the other rather than merging them.

No web scraping for the MVP: capability text comes from the company name + its
awards' CPV codes + the regions it has won in. Profile quality is therefore
thin (a known limitation — enrich later with dossier text / scraping); the
budget/location/qualification rule scores carry most of the early signal.

`source_company_id` is the idempotent upsert key, so re-running updates rather
than duplicates.
"""
from __future__ import annotations

from collections.abc import Sequence
from statistics import median

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Award, Company, CompanyProfile
from app.matching.embedder import EnsembleEmbedder
from app.matching.money import to_eur

# Cap on the concatenated capability text fed to the embedder (mirrors the v5
# trainer's 4000-char cap so in-app embeddings match the trained distribution).
_CAPABILITY_TEXT_CHARS = 4000


def derive_cpv_codes(awards: Sequence[Award]) -> list[str]:
    """Distinct CPV codes across a company's awards, order-preserved."""
    seen: dict[str, None] = {}
    for award in awards:
        if award.cpv_code:
            seen.setdefault(str(award.cpv_code).strip(), None)
    return list(seen)


def derive_nuts_codes(awards: Sequence[Award]) -> list[str]:
    """Distinct NUTS region codes across a company's awards (place of
    performance / buyer region). Feeds the v5 nuts_exact / nuts_country
    features. Order-preserved, upper-cased."""
    seen: dict[str, None] = {}
    for award in awards:
        nuts = getattr(award, "nuts_code", None)
        if nuts:
            seen.setdefault(str(nuts).strip().upper(), None)
    return list(seen)


def derive_deal_size(awards: Sequence[Award]) -> dict[str, float | None]:
    """Min/max/median contract value in **EUR** — the company's demonstrated range.

    Award values are stored in their own `contract_currency` (TED does not
    convert) and use -1/0 sentinels, so each is run through `to_eur` first (G7):
    values with an unknown/blank currency or a non-positive sentinel are dropped.
    Median feeds the v5 value_score (log-proximity to median)."""
    values = [
        v
        for v in (to_eur(a.contract_value_eur, a.contract_currency) for a in awards)
        if v is not None
    ]
    if not values:
        return {"min": None, "max": None, "median": None}
    return {
        "min": float(min(values)),
        "max": float(max(values)),
        "median": float(median(values)),
    }


def derive_regions(company: Company, awards: Sequence[Award]) -> list[str]:
    """Distinct regions the company is associated with (its own country + the
    buyer countries it has won contracts in)."""
    seen: dict[str, None] = {}
    if company.country:
        seen.setdefault(str(company.country).strip(), None)
    for award in awards:
        if award.buyer_country:
            seen.setdefault(str(award.buyer_country).strip(), None)
    return list(seen)


def build_capability_text(company: Company, awards: Sequence[Award]) -> str:
    """Text embedded for semantic matching (G6).

    Concatenates each award's `notice_title` + `description` (the original-language
    procurement text — the richest semantic signal), capped at
    ``_CAPABILITY_TEXT_CHARS``. This mirrors the v5 trainer's company-profile text,
    so the in-app embeddings match the distribution the LR's semantic coefficient
    was trained on. Falls back to the company name when no award text is available
    (older awards predating the enrichment columns). CPV/NUTS/region/value are not
    in the text — they are captured as structured features instead.
    """
    chunks: list[str] = []
    for award in awards:
        parts = [
            str(p).strip()
            for p in (award.notice_title, award.description)
            if p and str(p).strip()
        ]
        if parts:
            chunks.append(" ".join(parts))
    blob = " ".join(chunks)[:_CAPABILITY_TEXT_CHARS].strip()
    return blob or company.canonical_name


def build_company_profiles(
    session: Session,
    embedder: EnsembleEmbedder | None = None,
    limit: int | None = None,
    force_reembed: bool = False,
) -> dict[str, int]:
    """Derive/refresh a `company_profiles` row for each award-winner company.

    Returns a summary: ``{processed, created, updated, embedded}``. `embedder` is
    injectable so tests can pass a fake (avoiding the MiniLM download).

    Embedding is the slow part (~ms per profile × 15k), so it is **skipped when
    the capability text is unchanged** from the stored profile — re-running to
    refresh only the structured capability fields (CPV/NUTS/value/size) no longer
    re-encodes the whole pool. Pass ``force_reembed=True`` after switching the
    embedding model to rebuild every vector.
    """
    embedder = embedder or EnsembleEmbedder()
    summary = {"processed": 0, "created": 0, "updated": 0, "embedded": 0}

    company_stmt = sa.select(Company).order_by(Company.id)
    if limit is not None:
        company_stmt = company_stmt.limit(limit)

    for company in session.scalars(company_stmt).all():
        awards = session.scalars(
            sa.select(Award).where(Award.winner_canonical_id == company.id).order_by(Award.id)
        ).all()

        capability_text = build_capability_text(company, awards)
        capabilities = {
            "text": capability_text,
            "cpv_codes": derive_cpv_codes(awards),
            "nuts_codes": derive_nuts_codes(awards),
            "deal_size_eur": derive_deal_size(awards),
            "regions": derive_regions(company, awards),
            "award_count": len(awards),
        }

        profile = session.scalars(
            sa.select(CompanyProfile).where(CompanyProfile.source_company_id == company.id)
        ).first()
        if profile is None:
            profile = CompanyProfile(source_company_id=company.id)
            session.add(profile)
            summary["created"] += 1
            needs_embed = True
        else:
            summary["updated"] += 1
            prev_text = (profile.capabilities or {}).get("text")
            needs_embed = (
                force_reembed or profile.embedding is None or prev_text != capability_text
            )

        profile.name = company.canonical_name
        profile.country = company.country
        profile.capabilities = capabilities
        if needs_embed:
            profile.embedding = embedder.embed(capability_text)
            summary["embedded"] += 1
        summary["processed"] += 1

    session.commit()
    return summary
