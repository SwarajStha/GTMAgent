"""Unit tests for the Understanding-layer ExtractionValidator (pure, no deps)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.understanding.schemas import TenderProfile
from app.understanding.validator import ExtractionValidator


def _profile(**kw: object) -> TenderProfile:
    base = {"cpv_code": "45215130", "title": "Clinic construction"}
    base.update(kw)
    return TenderProfile(**base)


def test_valid_profile_passes_and_pads_cpv() -> None:
    profile = _profile(cpv_code="452151")
    ok, issues = ExtractionValidator().validate_tender(profile)
    assert ok is True
    assert profile.cpv_code == "45215100"  # padded to 8 digits
    assert issues == []


def test_missing_cpv_is_blocking() -> None:
    ok, issues = ExtractionValidator().validate_tender(_profile(cpv_code=""))
    assert ok is False
    assert any("CPV" in i for i in issues)


def test_short_cpv_is_blocking() -> None:
    ok, issues = ExtractionValidator().validate_tender(_profile(cpv_code="45"))
    assert ok is False


def test_sentinel_budget_is_dropped() -> None:
    profile = _profile(budget_eur=-1.0)
    ok, issues = ExtractionValidator().validate_tender(profile)
    assert ok is True  # non-blocking repair
    assert profile.budget_eur is None
    assert any("budget" in i for i in issues)


def test_implausible_budget_is_dropped() -> None:
    profile = _profile(budget_eur=5e11)
    ExtractionValidator().validate_tender(profile)
    assert profile.budget_eur is None


def test_past_deadline_is_flagged_not_blocking() -> None:
    past = (datetime.now(UTC) - timedelta(days=10)).date()
    profile = _profile(deadline=past)
    ok, issues = ExtractionValidator().validate_tender(profile)
    assert ok is True
    assert any("deadline" in i for i in issues)


def test_future_deadline_not_flagged() -> None:
    future = date(2099, 1, 1)
    _, issues = ExtractionValidator().validate_tender(_profile(deadline=future))
    assert not any("deadline" in i for i in issues)


def test_list_fields_deduped() -> None:
    profile = _profile(
        required_certifications=["ISO 9001", "iso 9001", " ISO 14001 ", ""],
        keywords=["a", "a", "b"],
    )
    ExtractionValidator().validate_tender(profile)
    assert profile.required_certifications == ["ISO 9001", "ISO 14001"]
    assert profile.keywords == ["a", "b"]
