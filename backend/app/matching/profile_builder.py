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

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Award, Company, CompanyProfile
from app.matching.embedder import EnsembleEmbedder


def derive_cpv_codes(awards: Sequence[Award]) -> list[str]:
    """Distinct CPV codes across a company's awards, order-preserved."""
    seen: dict[str, None] = {}
    for award in awards:
        if award.cpv_code:
            seen.setdefault(str(award.cpv_code).strip(), None)
    return list(seen)


def derive_deal_size(awards: Sequence[Award]) -> dict[str, float | None]:
    """Min/max observed contract value (EUR) — the company's demonstrated range."""
    values = [a.contract_value_eur for a in awards if a.contract_value_eur is not None]
    if not values:
        return {"min": None, "max": None}
    return {"min": float(min(values)), "max": float(max(values))}


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
    """A short natural-language capability blurb to embed for semantic matching."""
    cpvs = derive_cpv_codes(awards)
    regions = derive_regions(company, awards)
    parts = [company.canonical_name]
    if cpvs:
        parts.append("Public procurement categories (CPV): " + ", ".join(cpvs))
    if regions:
        parts.append("Has delivered public contracts in: " + ", ".join(regions))
    parts.append(f"Track record of {len(awards)} awarded public contract(s).")
    return ". ".join(parts)


def build_company_profiles(
    session: Session,
    embedder: EnsembleEmbedder | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Derive/refresh a `company_profiles` row for each award-winner company.

    Returns a summary: ``{processed, created, updated}``. `embedder` is
    injectable so tests can pass a fake (avoiding the MiniLM download).
    """
    embedder = embedder or EnsembleEmbedder()
    summary = {"processed": 0, "created": 0, "updated": 0}

    company_stmt = sa.select(Company).order_by(Company.id)
    if limit is not None:
        company_stmt = company_stmt.limit(limit)

    for company in session.scalars(company_stmt).all():
        awards = session.scalars(
            sa.select(Award).where(Award.winner_canonical_id == company.id)
        ).all()

        capability_text = build_capability_text(company, awards)
        capabilities = {
            "text": capability_text,
            "cpv_codes": derive_cpv_codes(awards),
            "deal_size_eur": derive_deal_size(awards),
            "regions": derive_regions(company, awards),
        }
        embedding = embedder.embed(capability_text)

        profile = session.scalars(
            sa.select(CompanyProfile).where(CompanyProfile.source_company_id == company.id)
        ).first()
        if profile is None:
            profile = CompanyProfile(source_company_id=company.id)
            session.add(profile)
            summary["created"] += 1
        else:
            summary["updated"] += 1

        profile.name = company.canonical_name
        profile.country = company.country
        profile.capabilities = capabilities
        profile.embedding = embedding
        summary["processed"] += 1

    session.commit()
    return summary
