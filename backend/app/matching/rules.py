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

from typing import Any

# Neutral fill for a dimension we cannot evaluate (missing data on either side).
MISSING_FILL = 0.5

# The penalty score for a company outside the tender's region (ML-spike value).
OUT_OF_REGION = 0.2


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


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
    """Fraction of the tender's required terms (CPV codes / capability keywords)
    the company can cover.

    A term counts as covered if it appears (as a substring) in the company's
    combined capability text, or shares a whole-word token with it. No tender
    requirements -> 1.0 (nothing to fail against).
    """
    required = [str(t).strip().lower() for t in (tender_terms or []) if str(t).strip()]
    if not required:
        return 1.0
    held_text = " ".join(str(t).strip().lower() for t in (company_terms or []) if str(t).strip())
    if not held_text:
        return 0.0
    held_tokens = set(held_text.split())
    matched = 0
    for term in required:
        term_tokens = set(term.split())
        if term in held_text or (term_tokens & held_tokens):
            matched += 1
    return round(matched / len(required), 4)


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
