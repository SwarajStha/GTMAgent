"""Tests for the Layer 1 supplier-pool builder.

Pure derivation helpers are tested directly; the DB builder runs against the
real `gtm_test` schema with a fake embedder (no MiniLM download).
"""
from __future__ import annotations

from datetime import date

from app.db.models import Award, Company, CompanyProfile
from app.matching.profile_builder import (
    build_capability_text,
    build_company_profiles,
    derive_cpv_codes,
    derive_deal_size,
    derive_regions,
)


class _FakeEmbedder:
    """Returns a fixed 384-d vector so we never load MiniLM in tests."""

    def __init__(self, fill: float = 0.1) -> None:
        self.fill = fill
        self.calls: list[str] = []

    def embed(self, text: str, model: str = "all-MiniLM-L6-v2") -> list[float]:
        self.calls.append(text)
        return [self.fill] * 384


def _company(**kw: object) -> Company:
    base = {"canonical_name": "Build GmbH", "resolution_key": "build", "country": "DE"}
    base.update(kw)
    return Company(**base)


def _award(company_id: int, ted_notice_id: str, **kw: object) -> Award:
    base = {
        "ted_notice_id": ted_notice_id,
        "winner_raw_name": "Build GmbH",
        "winner_canonical_id": company_id,
        "cpv_code": "45000000",
        "buyer_country": "DE",
        "contract_value_eur": 100_000.0,
        "award_date": date(2026, 1, 1),
        "raw_json": {"publication-number": ted_notice_id},
    }
    base.update(kw)
    return Award(**base)


# ── pure helpers ───────────────────────────────────────────────────────────


def test_derive_cpv_codes_dedupes() -> None:
    awards = [
        _award(1, "A-1", cpv_code="45000000"),
        _award(1, "A-2", cpv_code="45000000"),
        _award(1, "A-3", cpv_code="72000000"),
    ]
    assert derive_cpv_codes(awards) == ["45000000", "72000000"]


def test_derive_deal_size_min_max_median() -> None:
    awards = [
        _award(1, "A-1", contract_value_eur=50_000.0),
        _award(1, "A-2", contract_value_eur=250_000.0),
        _award(1, "A-3", contract_value_eur=None),
    ]
    assert derive_deal_size(awards) == {"min": 50_000.0, "max": 250_000.0, "median": 150_000.0}


def test_derive_deal_size_empty() -> None:
    assert derive_deal_size([]) == {"min": None, "max": None, "median": None}


def test_derive_regions_includes_company_and_buyer_countries() -> None:
    company = _company(country="DE")
    awards = [_award(1, "A-1", buyer_country="DE"), _award(1, "A-2", buyer_country="FR")]
    assert derive_regions(company, awards) == ["DE", "FR"]


def test_build_capability_text_mentions_name_and_cpv() -> None:
    text = build_capability_text(_company(canonical_name="Bembé Parkett"), [_award(1, "A-1")])
    assert "Bembé Parkett" in text
    assert "45000000" in text


# ── DB builder ─────────────────────────────────────────────────────────────


def test_build_company_profiles_creates_and_is_idempotent(db_session) -> None:
    company = _company()
    db_session.add(company)
    db_session.flush()
    db_session.add_all([
        _award(company.id, "A-1", contract_value_eur=50_000.0, cpv_code="45000000"),
        _award(company.id, "A-2", contract_value_eur=250_000.0, cpv_code="72000000"),
    ])
    db_session.flush()

    fake = _FakeEmbedder()
    summary = build_company_profiles(db_session, embedder=fake)
    assert summary == {"processed": 1, "created": 1, "updated": 0, "embedded": 1}

    profile = (
        db_session.query(CompanyProfile).filter_by(source_company_id=company.id).one()
    )
    assert profile.name == "Build GmbH"
    assert profile.country == "DE"
    assert profile.capabilities["cpv_codes"] == ["45000000", "72000000"]
    assert profile.capabilities["deal_size_eur"] == {
        "min": 50_000.0, "max": 250_000.0, "median": 150_000.0,
    }
    assert profile.capabilities["award_count"] == 2
    assert list(profile.embedding) == [0.1] * 384

    # Re-run with unchanged capability text: updates structured fields but
    # SKIPS re-embedding (embedded=0, embedder not called again), no duplicate.
    summary2 = build_company_profiles(db_session, embedder=fake)
    assert summary2 == {"processed": 1, "created": 0, "updated": 1, "embedded": 0}
    assert len(fake.calls) == 1  # embedded only on the first run
    count = db_session.query(CompanyProfile).filter_by(source_company_id=company.id).count()
    assert count == 1

    # force_reembed=True re-encodes even when text is unchanged.
    summary3 = build_company_profiles(db_session, embedder=fake, force_reembed=True)
    assert summary3 == {"processed": 1, "created": 0, "updated": 1, "embedded": 1}
    assert len(fake.calls) == 2
