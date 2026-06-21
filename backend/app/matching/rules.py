"""Rule-based sub-scorers (budget, location, qualification).

Pure, dependency-free functions returning a value in [0, 1]. Ported and adapted
from the `feat/gtm-lead-scoring-v2` ML spike and mapped onto three of the four
`matches` score columns — semantic lives in `semantic.py`; these provide
`budget_score`, `location_score`, and `qualification_score`.

Company capability data is read from the `company_profiles.capabilities` JSONB
written by the supplier-pool builder (Layer 1), shaped as::

    {
      "text": str,                       # capability description (also embedded)
      "cpv_codes": [str],                # CPV codes from the company's awards
      "deal_size_eur": {"min": float | None, "max": float | None},
      "regions": [str],                  # served regions / countries
    }
"""
from __future__ import annotations

import re
from typing import Any

# Neutral fill for a dimension we cannot evaluate (missing data on either side).
MISSING_FILL = 0.5

# The penalty score for a company outside the tender's region (ML-spike value).
OUT_OF_REGION = 0.2

# CPV-prefix partial-credit ladder (finest first). CPV codes are hierarchical
# (division=2, group=3, class=4, category=5, then detail up to 8 digits), so two
# codes that share only the leading digits are still related work. An exact
# 8-digit hit scores 1.0; sharing the 45-division ("construction") scores 0.3.
# This replaces exact-only CPV matching, which scored qualification=0 for every
# match in the live smoke (tender/award CPVs rarely match to all 8 digits).
_CPV_LEVELS: tuple[tuple[int, float], ...] = ((8, 1.0), (5, 0.8), (4, 0.6), (3, 0.4), (2, 0.3))


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _cpv_digits(term: str) -> str:
    """Return a normalised 8-digit CPV string if `term` looks like a CPV code,
    else ``""``. A CPV is all-numeric (a trailing ``-check`` digit / dots /
    spaces allowed) with at least 6 digits — so free-text like ``"parquet
    flooring"`` or ``"Construction of 45 houses"`` is NOT treated as a CPV."""
    raw = str(term).strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 6 and re.fullmatch(r"[\d\s.\-]+", raw):
        return digits[:8].ljust(8, "0")
    return ""


def _cpv_prefix_credit(tender_cpv: str, company_cpvs: list[str]) -> float:
    """Best partial-credit match of one tender CPV against the company's CPVs."""
    for level, credit in _CPV_LEVELS:
        if any(tender_cpv[:level] == c[:level] for c in company_cpvs):
            return credit
    return 0.0


def score_budget(
    tender_budget_eur: float | None,
    deal_min: float | None,
    deal_max: float | None,
) -> float:
    """1.0 inside the company's target deal-size range; linear decay outside.

    Unknown tender budget returns ``MISSING_FILL`` (we cannot judge fit).
    """
    if tender_budget_eur is None:
        return MISSING_FILL
    lo = deal_min if deal_min is not None else 0.0
    hi = deal_max if deal_max is not None else float("inf")
    if lo <= tender_budget_eur <= hi:
        return 1.0
    if tender_budget_eur < lo:
        return round(_clip01(tender_budget_eur / lo), 4) if lo > 0 else MISSING_FILL
    # tender_budget_eur > hi
    return round(_clip01(hi / tender_budget_eur), 4) if hi not in (0.0, float("inf")) else 1.0


def score_location(
    tender_country: str | None,
    company_country: str | None,
    company_regions: list[str] | None = None,
) -> float:
    """1.0 if the tender's country matches the company's country or a served
    region (substring either way), else ``OUT_OF_REGION``. Unknown tender
    country returns ``MISSING_FILL``.
    """
    if not tender_country or not str(tender_country).strip():
        return MISSING_FILL
    target = str(tender_country).strip().lower()
    candidates: list[str] = []
    if company_country:
        candidates.append(str(company_country).strip().lower())
    for region in company_regions or []:
        if region and str(region).strip():
            candidates.append(str(region).strip().lower())
    for candidate in candidates:
        if candidate and (candidate in target or target in candidate):
            return 1.0
    return OUT_OF_REGION


def score_qualification(
    tender_terms: list[str] | None,
    company_terms: list[str] | None,
) -> float:
    """Average coverage of the tender's required terms by the company.

    Each required term is classified and scored independently, then averaged:

    * **CPV codes** get hierarchical partial credit against the company's CPV
      codes (8-digit exact = 1.0 down to shared 2-digit division = 0.3) — see
      ``_CPV_LEVELS``. This is the fix for the live-smoke ``qualification=0``
      finding: construction tenders/awards share the ``45`` division but rarely
      an exact 8-digit code.
    * **Free-text keywords** get binary coverage: 1.0 if the phrase is a
      substring of, or shares a whole-word token with, the company's combined
      capability text; else 0.0.

    No tender requirements -> 1.0 (nothing to fail against).
    """
    required = [str(t).strip() for t in (tender_terms or []) if str(t).strip()]
    if not required:
        return 1.0

    # Split tender requirements into CPV codes vs free-text keywords.
    tender_cpvs = [d for d in (_cpv_digits(t) for t in required) if d]
    tender_keywords = [t for t in required if not _cpv_digits(t)]

    # Company side: structured CPV codes (matched by prefix) and a free-text blob
    # (matched by keyword overlap). CPV codes arrive as their own list items;
    # the capability text arrives as a single non-numeric item.
    held = [str(t).strip() for t in (company_terms or []) if str(t).strip()]
    company_cpvs = [d for d in (_cpv_digits(t) for t in held) if d]
    company_text = " ".join(t.lower() for t in held if not _cpv_digits(t))
    held_tokens = set(company_text.split())

    credits: list[float] = []
    for tc in tender_cpvs:
        credits.append(_cpv_prefix_credit(tc, company_cpvs) if company_cpvs else 0.0)
    for kw in tender_keywords:
        kw_lower = kw.lower()
        kw_tokens = set(kw_lower.split())
        covered = bool(company_text) and (kw_lower in company_text or bool(kw_tokens & held_tokens))
        credits.append(1.0 if covered else 0.0)

    return round(sum(credits) / len(credits), 4) if credits else 1.0


class RuleScorer:
    """Computes the three rule sub-scores for one (tender, company) pair.

    `capabilities` is the `company_profiles.capabilities` JSONB dict (see module
    docstring); `tender_terms` are the tender's CPV codes plus any extracted
    capability keywords.
    """

    def score(
        self,
        *,
        tender_budget_eur: float | None,
        tender_country: str | None,
        tender_terms: list[str] | None,
        company_country: str | None,
        capabilities: dict[str, Any] | None,
    ) -> dict[str, float]:
        caps = capabilities or {}
        deal = caps.get("deal_size_eur") or {}
        company_terms: list[str] = [str(c) for c in (caps.get("cpv_codes") or [])]
        if caps.get("text"):
            company_terms.append(str(caps["text"]))
        return {
            "budget_score": score_budget(tender_budget_eur, deal.get("min"), deal.get("max")),
            "location_score": score_location(
                tender_country, company_country, caps.get("regions")
            ),
            "qualification_score": score_qualification(tender_terms, company_terms),
        }
