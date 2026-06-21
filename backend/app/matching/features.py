"""v5 feature engineering — the 10 features the Logistic Regression ranks on.

Ported from the offline `exports_ml_pipeline.py` (v5) so the in-app matcher
computes *exactly* the features the committed model was trained on, then applies
the exported coefficients (see `lr_weights.py`). Definitions are kept identical
to v5; the only adaptation is the data source — here the company side reads the
`company_profiles.capabilities` JSONB built by `profile_builder` rather than the
CSV export.

Feature order in `FEATURE_NAMES` is load-bearing: it must match
`exports/model_params.json["feature_names"]`.

Live-tender caveat: real contract-notice tenders often lack a NUTS code and a
budget, so `nuts_*` and `value_*` fall back to the 0.5 "unknown" fill exactly as
v5 does when a field is missing — the model then leans on its strongest learned
signals (CPV-4, semantic, country).
"""
from __future__ import annotations

import math
import re
from typing import Any

FEATURE_NAMES: list[str] = [
    "semantic_score",
    "cpv_4digit_score",
    "cpv_2digit_score",
    "nuts_exact_score",
    "nuts_country_score",
    "value_score",
    "value_in_range_score",
    "country_match_score",
    "company_size_score",
    "competition_score",
]

# Neutral fill for a feature we cannot evaluate (data missing on either side).
UNKNOWN = 0.5


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _norm_cpv(cpv: str) -> str:
    """Digits only, padded/truncated to 8 (v5 `_norm_cpv`). '' if no digits."""
    digits = re.sub(r"\D", "", str(cpv))
    return digits[:8].ljust(8, "0") if digits else ""


def cpv_features(
    tender_cpvs: list[str] | None, company_cpvs: list[str] | None
) -> tuple[float, float]:
    """(cpv_4digit, cpv_2digit) — 1.0 match / 0.0 no-match / 0.5 unknown.

    v5 scored a single tender CPV; live tenders can carry several, so we take the
    best (any-match) across them at each prefix level.
    """
    t = [c for c in (_norm_cpv(x) for x in (tender_cpvs or [])) if c]
    c = [c for c in (_norm_cpv(x) for x in (company_cpvs or [])) if c]
    if not t or not c:
        return UNKNOWN, UNKNOWN
    c4 = {x[:4] for x in c}
    c2 = {x[:2] for x in c}
    return (
        1.0 if any(tc[:4] in c4 for tc in t) else 0.0,
        1.0 if any(tc[:2] in c2 for tc in t) else 0.0,
    )


def nuts_features(tender_nuts: str | None, company_nuts: list[str] | None) -> tuple[float, float]:
    """(nuts_exact NUTS-2/4, nuts_country) — 1.0 / 0.0 / 0.5 unknown (v5)."""
    if not tender_nuts or not company_nuts:
        return UNKNOWN, UNKNOWN
    t4 = str(tender_nuts)[:4].upper()
    t2 = str(tender_nuts)[:2].upper()
    c4 = {str(n)[:4].upper() for n in company_nuts}
    c2 = {str(n)[:2].upper() for n in company_nuts}
    return (
        1.0 if t4 in c4 else 0.0,
        1.0 if t2 in c2 else 0.0,
    )


def value_features(
    tender_eur: float | None,
    company_median: float | None,
    company_min: float | None = None,
    company_max: float | None = None,
) -> tuple[float, float]:
    """(value_score log-proximity, value_in_range) — v5 `value_features`."""
    if tender_eur is None or company_median is None or company_median <= 0:
        return UNKNOWN, UNKNOWN
    log_ratio = abs(math.log10(max(tender_eur / company_median, 1e-6)))
    v_score = _clip01(1.0 - 0.25 * log_ratio)
    if company_min is not None and company_max is not None:
        in_range = 1.0 if (company_min * 0.1) <= tender_eur <= (company_max * 10) else 0.0
    else:
        in_range = v_score
    return v_score, in_range


def country_match_score(tender_country: str | None, company_countries: list[str] | None) -> float:
    """1.0 if the tender's country is among the company's countries/regions (v5)."""
    if not tender_country or not company_countries:
        return UNKNOWN
    tc = str(tender_country).strip().upper()
    return 1.0 if tc in [str(c).upper() for c in company_countries] else 0.0


def company_size_score(award_count: int) -> float:
    """Log-scaled activity, capped at 100 awards → 1.0 (v5)."""
    if award_count <= 0:
        return 0.0
    return _clip01(math.log1p(award_count) / math.log1p(100))


def compute_features(
    *,
    semantic_score: float,
    tender_cpvs: list[str] | None,
    tender_nuts: str | None,
    tender_budget_eur: float | None,
    tender_country: str | None,
    capabilities: dict[str, Any] | None,
) -> dict[str, float]:
    """Compute all 10 v5 features for one (tender, company_profile) pair.

    `semantic_score` is the clipped cosine of the two embeddings (computed by the
    pipeline, which holds both vectors). `capabilities` is the
    `company_profiles.capabilities` JSONB (cpv_codes / nuts_codes /
    deal_size_eur{min,max,median} / regions / award_count).
    """
    caps = capabilities or {}
    deal = caps.get("deal_size_eur") or {}
    cpv4, cpv2 = cpv_features(tender_cpvs, caps.get("cpv_codes"))
    nuts_exact, nuts_country = nuts_features(tender_nuts, caps.get("nuts_codes"))
    value, value_in_range = value_features(
        tender_budget_eur, deal.get("median"), deal.get("min"), deal.get("max")
    )
    return {
        "semantic_score": _clip01(float(semantic_score)),
        "cpv_4digit_score": cpv4,
        "cpv_2digit_score": cpv2,
        "nuts_exact_score": nuts_exact,
        "nuts_country_score": nuts_country,
        "value_score": value,
        "value_in_range_score": value_in_range,
        "country_match_score": country_match_score(tender_country, caps.get("regions")),
        "company_size_score": company_size_score(int(caps.get("award_count") or 0)),
        "competition_score": UNKNOWN,  # n_offers unknown at prediction time (v5)
    }


def feature_vector(features: dict[str, float], names: list[str] | None = None) -> list[float]:
    """Order a feature dict into a vector matching `names` (default FEATURE_NAMES)."""
    return [float(features[n]) for n in (names or FEATURE_NAMES)]
