"""Unit tests for the v5 feature engineering (pure, no ML deps)."""
from __future__ import annotations

from app.matching.features import (
    FEATURE_NAMES,
    company_size_score,
    compute_features,
    country_match_score,
    cpv_features,
    feature_vector,
    nuts_features,
    value_features,
)

# ── cpv ─────────────────────────────────────────────────────────────────────


def test_cpv_features_4_and_2_digit_match() -> None:
    # tender 45233223 vs company 45233000 share 4523 (and 45).
    assert cpv_features(["45233223"], ["45233000"]) == (1.0, 1.0)


def test_cpv_features_division_only() -> None:
    # 45215130 vs 45432200 share only the 45 division.
    assert cpv_features(["45215130"], ["45432200"]) == (0.0, 1.0)


def test_cpv_features_no_overlap() -> None:
    assert cpv_features(["45000000"], ["72000000"]) == (0.0, 0.0)


def test_cpv_features_unknown_when_missing() -> None:
    assert cpv_features([], ["45000000"]) == (0.5, 0.5)
    assert cpv_features(["45000000"], []) == (0.5, 0.5)


def test_cpv_features_best_across_multiple_tender_cpvs() -> None:
    # one tender CPV matches at 4-digit even if another doesn't.
    assert cpv_features(["72000000", "45233223"], ["45233000"]) == (1.0, 1.0)


# ── nuts ────────────────────────────────────────────────────────────────────


def test_nuts_features_unknown_when_tender_has_none() -> None:
    assert nuts_features(None, ["DE21"]) == (0.5, 0.5)
    assert nuts_features("DE21", []) == (0.5, 0.5)


def test_nuts_features_exact_and_country() -> None:
    assert nuts_features("DE21", ["DE21"]) == (1.0, 1.0)   # exact + country
    assert nuts_features("DE21", ["DE30"]) == (0.0, 1.0)   # country only


# ── value ───────────────────────────────────────────────────────────────────


def test_value_features_at_median_is_one() -> None:
    v, in_range = value_features(100_000, 100_000, 30_000, 500_000)
    assert v == 1.0
    assert in_range == 1.0


def test_value_features_unknown_without_median() -> None:
    assert value_features(100_000, None) == (0.5, 0.5)
    assert value_features(None, 100_000) == (0.5, 0.5)


def test_value_features_out_of_range() -> None:
    # tender 100x the company's whole historical max → out of [min*.1, max*10].
    _, in_range = value_features(100_000_000, 50_000, 10_000, 100_000)
    assert in_range == 0.0


# ── country / size ──────────────────────────────────────────────────────────


def test_country_match_score() -> None:
    assert country_match_score("DEU", ["DEU", "FRA"]) == 1.0
    assert country_match_score("DEU", ["FRA"]) == 0.0
    assert country_match_score("DEU", []) == 0.5
    assert country_match_score(None, ["DEU"]) == 0.5


def test_company_size_score_monotonic() -> None:
    assert company_size_score(0) == 0.0
    assert company_size_score(1) < company_size_score(10) < company_size_score(100)
    assert company_size_score(1000) == 1.0  # capped at 1.0


# ── compute_features / feature_vector ───────────────────────────────────────


def test_compute_features_returns_all_named_features() -> None:
    caps = {
        "cpv_codes": ["45233000"],
        "nuts_codes": [],
        "deal_size_eur": {"min": 30_000, "max": 500_000, "median": 100_000},
        "regions": ["DEU"],
        "award_count": 12,
    }
    f = compute_features(
        semantic_score=0.7,
        tender_cpvs=["45233223"],
        tender_nuts=None,
        tender_budget_eur=100_000,
        tender_country="DEU",
        capabilities=caps,
    )
    assert set(f) == set(FEATURE_NAMES)
    assert f["semantic_score"] == 0.7
    assert f["cpv_4digit_score"] == 1.0
    assert f["country_match_score"] == 1.0
    assert f["value_score"] == 1.0
    assert f["nuts_exact_score"] == 0.5  # tender has no NUTS
    assert f["competition_score"] == 0.5


def test_feature_vector_orders_by_feature_names() -> None:
    f = {name: float(i) for i, name in enumerate(FEATURE_NAMES)}
    assert feature_vector(f) == [float(i) for i in range(len(FEATURE_NAMES))]
