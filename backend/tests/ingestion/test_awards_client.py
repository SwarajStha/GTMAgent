"""Tests for ingestion.awards_client / entity_resolution / AwardRow."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Award, Company
from app.ingestion.awards_client import backfill_awards
from app.ingestion.entity_resolution import (
    clean_identifier,
    normalise_name,
    resolve_or_create,
)
from app.ingestion.schemas import AwardRow


@pytest.fixture
def session() -> Iterator[Session]:
    """In-memory SQLite session with only the two Job-2 tables created.

    `Base.metadata.create_all` would also try to build Postgres-only tables
    (pgvector `Vector`, JSONB, UUID FKs), so we create just what we need.
    """
    engine = create_engine("sqlite:///:memory:")
    Company.__table__.create(engine)
    Award.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)
    with factory() as s:
        yield s


# ---------- normalise_name -------------------------------------------------


def test_normalise_name_strips_gmbh() -> None:
    assert normalise_name("Hochtief GmbH") == "hochtief"


def test_normalise_name_strips_punctuation() -> None:
    assert normalise_name("A.B. Bau, AG") == "ab bau"


def test_normalise_name_empty_result_fallback() -> None:
    # Input is *only* a suffix — must not return an empty resolution key.
    assert normalise_name("GmbH") == "gmbh"


# ---------- resolve_or_create ---------------------------------------------


def test_resolve_or_create_new_company(session: Session) -> None:
    company = resolve_or_create(session, "Hochtief GmbH")
    session.flush()

    assert session.execute(select(Company)).scalars().all() == [company]
    assert company.canonical_name == "Hochtief GmbH"
    assert company.resolution_key == "hochtief"
    assert company.aliases == ["Hochtief GmbH"]


def test_resolve_or_create_existing_company(session: Session) -> None:
    first = resolve_or_create(session, "Hochtief GmbH")
    session.flush()
    second = resolve_or_create(session, "Hochtief GmbH")
    session.flush()

    assert session.scalar(select(Company.id).where(Company.id == first.id)) is not None
    assert session.query(Company).count() == 1
    assert second.id == first.id
    assert second.aliases == ["Hochtief GmbH"]


def test_resolve_or_create_deduplication(session: Session) -> None:
    resolve_or_create(session, "Hochtief AG")
    session.flush()
    company = resolve_or_create(session, "Hochtief Aktiengesellschaft")
    session.flush()

    assert session.query(Company).count() == 1
    assert "Hochtief AG" in company.aliases
    assert "Hochtief Aktiengesellschaft" in company.aliases


# ---------- identifier (tax-id) resolution --------------------------------


def test_clean_identifier_rejects_junk() -> None:
    # Real ids (digit-heavy) pass through, stripped.
    assert clean_identifier("DE123456") == "DE123456"
    assert clean_identifier("  B88428404 ") == "B88428404"
    assert clean_identifier("HRB131774 Charlottenburg") == "HRB131774 Charlottenburg"
    # Junk that would false-merge unrelated companies is rejected.
    assert clean_identifier("0") is None
    assert clean_identifier("000") is None
    assert clean_identifier("") is None
    assert clean_identifier(None) is None
    assert clean_identifier("keine Angabe") is None  # textual placeholder
    assert clean_identifier("n/a") is None
    assert clean_identifier("123") is None  # too few digits


def test_resolve_by_identifier_merges_name_variants(session: Session) -> None:
    # Same tax id, names that do NOT normalise alike — must still be one row.
    first = resolve_or_create(session, "Siemens AG", identifier="DE12345")
    session.flush()
    second = resolve_or_create(
        session, "Siemens Mobility España", identifier="DE12345"
    )
    session.flush()

    assert session.query(Company).count() == 1
    assert second.id == first.id
    assert "Siemens AG" in second.aliases
    assert "Siemens Mobility España" in second.aliases


def test_resolve_identifier_backfills_existing_name_match(session: Session) -> None:
    # A row created name-only later acquires an id — backfilled, not duplicated.
    first = resolve_or_create(session, "Hochtief GmbH")
    session.flush()
    assert first.registration_id is None

    second = resolve_or_create(session, "Hochtief GmbH", identifier="DE999111")
    session.flush()

    assert session.query(Company).count() == 1
    assert second.id == first.id
    assert second.registration_id == "DE999111"


def test_resolve_different_identifier_splits_same_name(session: Session) -> None:
    # Same trading name, different tax ids → two distinct legal entities.
    a = resolve_or_create(session, "Bau GmbH", identifier="AT12345")
    session.flush()
    b = resolve_or_create(session, "Bau GmbH", identifier="DE67890")
    session.flush()

    assert a.id != b.id
    assert session.query(Company).count() == 2


def test_resolve_junk_identifier_falls_back_to_name(session: Session) -> None:
    # Junk id ("0") is ignored; name dedup still collapses to one row.
    resolve_or_create(session, "Acme Ltd", identifier="0")
    session.flush()
    again = resolve_or_create(session, "Acme Ltd", identifier="0")
    session.flush()

    assert session.query(Company).count() == 1
    assert again.registration_id is None


# ---------- AwardRow.from_ted_response ------------------------------------


def test_from_award_response_all_fields() -> None:
    # Mirrors the real selec-w notice 82677-2026 shape: lists wrapping the
    # actual value (lot-level flattening), multilingual dict for the
    # winner's organisation name.
    raw = {
        "publication-number": "12345-2026",
        "classification-cpv": ["45000000"],
        "notice-title": {"eng": ["Germany – Erection works"]},
        "description-proc": {"deu": "Holzbauarbeiten mit Dachoberlichtern"},
        "procedure-type": "open",
        "place-of-performance-subdiv-proc": ["DE712"],
        "buyer-name": "Stadt Frankfurt",
        "buyer-country": ["DEU"],
        "organisation-name-tenderer": {"deu": ["Hochtief AG"]},
        "winner-identifier": ["DE811234567"],
        "winner-country": ["DEU"],
        "BT-720-Tender": ["5000000.00"],
        "BT-720-Tender-Currency": ["EUR"],
        "BT-145-Contract": ["2026-04-15+02:00"],
        "BT-759-LotResult": ["4"],
    }
    row = AwardRow.from_ted_response(raw)
    assert row is not None
    assert row.ted_notice_id == "12345-2026"
    assert row.cpv_code == "45000000"
    assert row.notice_title == "Germany – Erection works"
    assert row.description == "Holzbauarbeiten mit Dachoberlichtern"
    assert row.procedure_type == "open"
    assert row.nuts_code == "DE712"
    assert row.buyer_name == "Stadt Frankfurt"
    assert row.buyer_country == "DEU"
    assert row.winner_raw_name == "Hochtief AG"
    assert row.winner_identifier == "DE811234567"
    assert row.winner_country == "DEU"
    assert row.contract_value_eur == 5_000_000.0
    assert row.contract_currency == "EUR"
    assert row.award_date == date(2026, 4, 15)
    assert row.n_offers_received == 4
    assert row.raw_json == raw


def test_from_award_response_fallback_winner_key() -> None:
    # `organisation-name-tenderer` absent — falls back to `tendering-party-name`.
    raw = {
        "publication-number": "67890-2026",
        "tendering-party-name": ["Fallback Bau GmbH"],
    }
    row = AwardRow.from_ted_response(raw)
    assert row is not None
    assert row.winner_raw_name == "Fallback Bau GmbH"


def test_from_award_response_missing_optional_fields() -> None:
    raw = {
        "publication-number": "11111-2026",
        "organisation-name-tenderer": "Solo Winner Ltd",
    }
    row = AwardRow.from_ted_response(raw)
    assert row is not None
    assert row.contract_value_eur is None
    assert row.award_date is None
    assert row.n_offers_received is None


# ---------- backfill_awards (dry-run) -------------------------------------


def test_backfill_dry_run_no_db_write(monkeypatch: pytest.MonkeyPatch) -> None:
    # A normal winner notice, plus a clos-nw cancellation that must be
    # counted as `skipped_no_winner` (not as a parse error).
    page = {
        "notices": [
            {
                "publication-number": "a1-2026",
                "organisation-name-tenderer": "Acme GmbH",
                "BT-142-LotResult": ["selec-w"],
            },
            {
                "publication-number": "a2-2026",
                "organisation-name-tenderer": "Beta SA",
                "BT-142-LotResult": ["selec-w"],
            },
            {
                "publication-number": "cancelled-2026",
                "BT-142-LotResult": ["clos-nw", "clos-nw"],
            },
        ]
    }

    def fake_search_all(
        self, query: str, fields: list[str], limit_per_page: int = 100
    ):
        yield page

    monkeypatch.setattr(
        "app.ingestion.awards_client.TedClient.search_all_pages", fake_search_all
    )
    monkeypatch.setattr(
        "app.ingestion.awards_client.TedClient.__enter__", lambda self: self
    )
    monkeypatch.setattr(
        "app.ingestion.awards_client.TedClient.__exit__", lambda self, *a: None
    )
    # TedClient.__init__ touches httpx + truststore + settings; sidestep it.
    monkeypatch.setattr(
        "app.ingestion.awards_client.TedClient.__init__", lambda self: None
    )

    session_factory = MagicMock()
    monkeypatch.setattr("app.ingestion.awards_client.get_session", session_factory)

    summary = backfill_awards(cpv_codes=["45000000"], dry_run=True)

    assert summary["fetched"] == 2
    assert summary["new"] == 0
    assert summary["updated"] == 0
    assert summary["companies_created"] == 0
    assert summary["skipped_no_winner"] == 1
    assert summary["errors"] == 0
    assert not session_factory.called
