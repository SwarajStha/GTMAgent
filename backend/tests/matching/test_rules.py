"""Unit tests for the rule-based sub-scorers (pure, no ML deps)."""
from __future__ import annotations

from app.matching.rules import (
    MISSING_FILL,
    OUT_OF_REGION,
    RuleScorer,
    score_budget,
    score_location,
    score_qualification,
)

# ── budget ────────────────────────────────────────────────────────────────


def test_budget_inside_range_is_one() -> None:
    assert score_budget(100_000, 30_000, 500_000) == 1.0


def test_budget_below_range_decays() -> None:
    # 15k against a 30k floor -> 0.5
    assert score_budget(15_000, 30_000, 500_000) == 0.5


def test_budget_above_range_decays() -> None:
    # 1,000,000 against a 500k ceiling -> 0.5
    assert score_budget(1_000_000, 30_000, 500_000) == 0.5


def test_budget_unknown_is_missing_fill() -> None:
    assert score_budget(None, 30_000, 500_000) == MISSING_FILL


def test_budget_open_ceiling_above_floor_is_one() -> None:
    assert score_budget(10_000_000, 30_000, None) == 1.0


# ── location ──────────────────────────────────────────────────────────────


def test_location_country_match() -> None:
    assert score_location("Germany", "Germany") == 1.0


def test_location_substring_match_either_way() -> None:
    assert score_location("Bad Soden, Germany", None, ["germany"]) == 1.0
    assert score_location("DE", None, ["DE-Bayern"]) == 1.0


def test_location_no_match_is_penalised() -> None:
    assert score_location("France", "Germany", ["Bayern"]) == OUT_OF_REGION


def test_location_unknown_tender_country_is_missing_fill() -> None:
    assert score_location("", "Germany") == MISSING_FILL
    assert score_location(None, "Germany") == MISSING_FILL


# ── qualification ─────────────────────────────────────────────────────────


def test_qualification_no_requirements_is_one() -> None:
    assert score_qualification([], ["anything"]) == 1.0
    assert score_qualification(None, None) == 1.0


def test_qualification_full_cpv_overlap() -> None:
    assert score_qualification(["45000000"], ["45000000", "72000000"]) == 1.0


def test_qualification_partial_overlap() -> None:
    # one of two required terms covered -> 0.5
    assert score_qualification(["45000000", "98000000"], ["45000000"]) == 0.5


def test_qualification_keyword_token_overlap() -> None:
    assert score_qualification(["parquet flooring"], ["specialist parquet contractor"]) == 1.0


def test_qualification_company_has_nothing() -> None:
    assert score_qualification(["45000000"], []) == 0.0


# ── RuleScorer wrapper ────────────────────────────────────────────────────


def test_rule_scorer_reads_capabilities_dict() -> None:
    caps = {
        "text": "parquet and flooring works for public buildings",
        "cpv_codes": ["45000000"],
        "deal_size_eur": {"min": 30_000, "max": 500_000},
        "regions": ["Germany", "Bayern"],
    }
    scores = RuleScorer().score(
        tender_budget_eur=100_000,
        tender_country="Bad Soden, Germany",
        tender_terms=["45000000"],
        company_country="Germany",
        capabilities=caps,
    )
    assert scores == {
        "budget_score": 1.0,
        "location_score": 1.0,
        "qualification_score": 1.0,
    }


def test_rule_scorer_handles_missing_capabilities() -> None:
    scores = RuleScorer().score(
        tender_budget_eur=None,
        tender_country=None,
        tender_terms=["45000000"],
        company_country=None,
        capabilities=None,
    )
    assert scores["budget_score"] == MISSING_FILL
    assert scores["location_score"] == MISSING_FILL
    assert scores["qualification_score"] == 0.0
