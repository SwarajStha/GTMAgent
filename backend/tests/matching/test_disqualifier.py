"""Unit tests for the hard disqualifier gates (pure, no ML deps)."""
from __future__ import annotations

from app.matching.disqualifier import Disqualifier


def test_clean_pair_is_not_disqualified() -> None:
    ok, reasons = Disqualifier().check(
        tender_budget_eur=100_000,
        required_certifications=["ISO 9001"],
        company_certifications=["ISO 9001", "ISO 27001"],
        deal_max=500_000,
    )
    assert ok is False
    assert reasons == []


def test_missing_required_certification_disqualifies() -> None:
    ok, reasons = Disqualifier().check(
        required_certifications=["ISO 27001"],
        company_certifications=["ISO 9001"],
    )
    assert ok is True
    assert any("certification" in r for r in reasons)


def test_no_required_certs_never_fails_on_certs() -> None:
    ok, reasons = Disqualifier().check(
        required_certifications=[],
        company_certifications=[],
    )
    assert ok is False
    assert reasons == []


def test_budget_far_over_capacity_disqualifies() -> None:
    ok, reasons = Disqualifier().check(
        tender_budget_eur=6_000_000,
        deal_max=500_000,  # 12x capacity > 10x threshold
    )
    assert ok is True
    assert any("capacity" in r for r in reasons)


def test_budget_within_threshold_is_ok() -> None:
    ok, reasons = Disqualifier().check(
        tender_budget_eur=4_000_000,
        deal_max=500_000,  # 8x capacity < 10x threshold
    )
    assert ok is False
    assert reasons == []


def test_missing_budget_or_dealmax_does_not_gate() -> None:
    assert Disqualifier().check(tender_budget_eur=None, deal_max=500_000) == (False, [])
    assert Disqualifier().check(tender_budget_eur=9_000_000, deal_max=None) == (False, [])
