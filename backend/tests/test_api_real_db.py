"""Real-Postgres happy-path tests for the read/serve API layer.

The per-router test files (`test_tenders_api.py`, `test_matches_api.py`,
`test_awards_companies_api.py`, `test_feedback_api.py`) mock the DB with
`MagicMock` / `SimpleNamespace`, so they validate response *shaping* but never
touch a real schema — a handler referencing a column that doesn't exist still
passes (that's exactly how the `emails.py` `Document.created_at` bug shipped
green).

This module exercises each handler against the real `gtm_test` schema via the
`db_session` fixture (see `conftest.py`), inserting real ORM rows and calling
the handlers directly. Schema drift here fails loudly.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException

from app.api.v1.awards import get_award, list_awards
from app.api.v1.companies import get_company, list_companies
from app.api.v1.emails import generate_buyer_email, get_email
from app.api.v1.feedback import FeedbackCreate, submit_feedback
from app.api.v1.matches import get_match, list_matches
from app.api.v1.tenders import get_tender, list_tenders
from app.db.models import (
    Award,
    Company,
    CompanyProfile,
    Email,
    Feedback,
    Match,
    Tender,
)

# ---------------------------------------------------------------------------
# Row builders (real ORM instances)
# ---------------------------------------------------------------------------


def _make_tender(**overrides: object) -> Tender:
    base: dict[str, object] = {
        "ted_notice_id": "326612-2026",
        "title": "Construction technology platform",
        "buyer_name": "City Buyer",
        "buyer_country": "DE",
        "cpv_codes": ["45000000", "72000000"],
        "deadline": datetime(2026, 7, 1, tzinfo=UTC),
        "budget_eur": 1_500_000.0,
        "currency": "EUR",
        "document_url": "https://ted.europa.eu/notice/326612-2026",
        "raw_json": {"publication-number": "326612-2026"},
    }
    base.update(overrides)
    return Tender(**base)


def _make_company_profile(**overrides: object) -> CompanyProfile:
    base: dict[str, object] = {
        "name": "BuildFlow Systems",
        "country": "DE",
        "website": "https://buildflow.example",
        "capabilities": {"workflow": ["permitting", "BIM"]},
        "certifications": {"security": ["ISO 27001"]},
    }
    base.update(overrides)
    return CompanyProfile(**base)


def _make_match(tender_id: int, company_id, **overrides: object) -> Match:
    base: dict[str, object] = {
        "tender_id": tender_id,
        "company_id": company_id,
        "semantic_score": 0.94,
        "budget_score": 0.88,
        "location_score": 0.97,
        "qualification_score": 0.91,
        "final_score": 0.93,
        "weights": {"semantic": 0.5, "budget": 0.2},
        "explanation": "Strong product overlap with buyer needs.",
    }
    base.update(overrides)
    return Match(**base)


def _make_company(**overrides: object) -> Company:
    base: dict[str, object] = {
        "canonical_name": "Build GmbH",
        "resolution_key": "build",
        "aliases": ["Build GmbH", "Build GesmbH"],
        "country": "DE",
    }
    base.update(overrides)
    return Company(**base)


def _make_award(winner_canonical_id: int | None = None, **overrides: object) -> Award:
    base: dict[str, object] = {
        "ted_notice_id": "123456-2026",
        "cpv_code": "45000000",
        "buyer_name": "City Buyer",
        "buyer_country": "DE",
        "winner_raw_name": "Build GmbH",
        "winner_canonical_id": winner_canonical_id,
        "contract_value_eur": 750_000.0,
        "award_date": date(2026, 5, 12),
        "n_offers_received": 4,
        "raw_json": {"publication-number": "123456-2026"},
    }
    base.update(overrides)
    return Award(**base)


# ---------------------------------------------------------------------------
# Tenders
# ---------------------------------------------------------------------------


def test_tenders_list_and_get_real_db(db_session) -> None:
    tender = _make_tender()
    db_session.add(tender)
    db_session.flush()

    listed = list_tenders(db=db_session)
    assert listed.total >= 1
    assert any(item.ted_notice_id == "326612-2026" for item in listed.items)

    by_id = get_tender(str(tender.id), db=db_session)
    assert by_id.id == tender.id
    assert by_id.raw_json == {"publication-number": "326612-2026"}

    by_notice = get_tender("326612-2026", db=db_session)
    assert by_notice.id == tender.id


def test_tenders_filters_real_db(db_session) -> None:
    db_session.add_all(
        [
            _make_tender(ted_notice_id="A-1", buyer_country="DE", cpv_codes=["45000000"]),
            _make_tender(ted_notice_id="B-2", buyer_country="FR", cpv_codes=["72000000"]),
        ]
    )
    db_session.flush()

    de_only = list_tenders(db=db_session, country="de")
    assert {i.ted_notice_id for i in de_only.items} == {"A-1"}

    cpv_only = list_tenders(db=db_session, cpv="72000000")
    assert {i.ted_notice_id for i in cpv_only.items} == {"B-2"}

    searched = list_tenders(db=db_session, q="A-1")
    assert {i.ted_notice_id for i in searched.items} == {"A-1"}


# ---------------------------------------------------------------------------
# Matches (+ linked email summary, + email detail)
# ---------------------------------------------------------------------------


def test_matches_list_and_detail_real_db(db_session) -> None:
    tender = _make_tender()
    company = _make_company_profile()
    db_session.add_all([tender, company])
    db_session.flush()

    match = _make_match(tender.id, company.id)
    db_session.add(match)
    db_session.flush()

    email = Email(
        match_id=match.id,
        subject="Munich BIM permitting tender",
        body="Hi team, we found a tender.",
        status="draft",
    )
    db_session.add(email)
    db_session.flush()

    listed = list_matches(db=db_session)
    assert listed.total >= 1
    row = next(i for i in listed.items if i.id == match.id)
    assert row.tender.ted_notice_id == "326612-2026"
    assert row.company.name == "BuildFlow Systems"
    assert row.final_score == 0.93

    detail = get_match(match.id, db=db_session)
    assert detail.emails[0].id == email.id
    assert detail.emails[0].subject == "Munich BIM permitting tender"

    fetched_email = get_email(email.id, db=db_session)
    assert fetched_email.match_id == match.id
    assert fetched_email.company.name == "BuildFlow Systems"


def test_matches_min_score_and_disqualified_filters_real_db(db_session) -> None:
    tender = _make_tender()
    company = _make_company_profile()
    db_session.add_all([tender, company])
    db_session.flush()

    db_session.add_all(
        [
            _make_match(tender.id, company.id, final_score=0.9),
            _make_match(tender.id, company.id, final_score=0.2),
            _make_match(tender.id, company.id, final_score=0.95, is_disqualified=True),
        ]
    )
    db_session.flush()

    high = list_matches(db=db_session, min_score=0.5)
    assert {round(i.final_score, 2) for i in high.items} == {0.9}

    with_dq = list_matches(db=db_session, include_disqualified=True, min_score=0.5)
    assert {round(i.final_score, 2) for i in with_dq.items} == {0.9, 0.95}


# ---------------------------------------------------------------------------
# Awards (+ winner canonical-name join)
# ---------------------------------------------------------------------------


def test_awards_list_and_get_real_db(db_session) -> None:
    company = _make_company()
    db_session.add(company)
    db_session.flush()

    award = _make_award(winner_canonical_id=company.id)
    db_session.add(award)
    db_session.flush()

    listed = list_awards(db=db_session)
    assert listed.total >= 1
    row = next(i for i in listed.items if i.ted_notice_id == "123456-2026")
    assert row.winner_canonical_name == "Build GmbH"

    detail = get_award(award.id, db=db_session)
    assert detail.raw_json == {"publication-number": "123456-2026"}
    assert detail.winner_canonical_name == "Build GmbH"

    by_winner = list_awards(db=db_session, winner_canonical_id=company.id)
    assert {i.ted_notice_id for i in by_winner.items} == {"123456-2026"}

    searched = list_awards(db=db_session, q="Build")
    assert any(i.ted_notice_id == "123456-2026" for i in searched.items)


def test_awards_unresolved_winner_real_db(db_session) -> None:
    """An award whose winner never resolved to a company (NULL FK) must still
    list cleanly, with a null canonical name via the LEFT OUTER JOIN."""
    award = _make_award(winner_canonical_id=None, ted_notice_id="UNRES-1")
    db_session.add(award)
    db_session.flush()

    row = next(i for i in list_awards(db=db_session).items if i.ted_notice_id == "UNRES-1")
    assert row.winner_canonical_id is None
    assert row.winner_canonical_name is None
    assert row.winner_raw_name == "Build GmbH"

    detail = get_award(award.id, db=db_session)
    assert detail.winner_canonical_name is None


# ---------------------------------------------------------------------------
# Companies (+ award-history rollups)
# ---------------------------------------------------------------------------


def test_companies_rollups_and_detail_real_db(db_session) -> None:
    company = _make_company()
    db_session.add(company)
    db_session.flush()

    db_session.add_all(
        [
            _make_award(
                winner_canonical_id=company.id,
                ted_notice_id="A-1",
                contract_value_eur=100_000.0,
                award_date=date(2026, 1, 1),
            ),
            _make_award(
                winner_canonical_id=company.id,
                ted_notice_id="A-2",
                contract_value_eur=250_000.0,
                award_date=date(2026, 5, 5),
            ),
        ]
    )
    db_session.flush()

    listed = list_companies(db=db_session)
    row = next(i for i in listed.items if i.id == company.id)
    assert row.award_count == 2
    assert row.total_contract_value_eur == 350_000.0
    assert row.latest_award_date == date(2026, 5, 5)

    detail = get_company(company.id, db=db_session)
    assert detail.award_count == 2
    assert {a.ted_notice_id for a in detail.recent_awards} == {"A-1", "A-2"}


def test_companies_zero_award_company_real_db(db_session) -> None:
    """LEFT JOIN aggregation must not choke when a company has no awards."""
    company = _make_company(canonical_name="Lonely Co", resolution_key="lonely")
    db_session.add(company)
    db_session.flush()

    row = next(i for i in list_companies(db=db_session).items if i.id == company.id)
    assert row.award_count == 0
    assert row.total_contract_value_eur is None
    assert row.latest_award_date is None

    detail = get_company(company.id, db=db_session)
    assert detail.award_count == 0
    assert detail.recent_awards == []


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


def test_feedback_submit_real_db(db_session) -> None:
    tender = _make_tender()
    company = _make_company_profile()
    db_session.add_all([tender, company])
    db_session.flush()

    match = _make_match(tender.id, company.id)
    db_session.add(match)
    db_session.flush()

    out = submit_feedback(
        FeedbackCreate(match_id=match.id, rating=1, comment="Good fit"),
        db=db_session,
    )
    assert out.match_id == match.id
    assert out.rating == 1
    assert out.email_id is None

    stored = db_session.get(Feedback, out.id)
    assert stored is not None
    assert stored.comment == "Good fit"


def test_feedback_submit_with_email_real_db(db_session) -> None:
    tender = _make_tender()
    company = _make_company_profile()
    db_session.add_all([tender, company])
    db_session.flush()

    match = _make_match(tender.id, company.id)
    db_session.add(match)
    db_session.flush()

    email = Email(match_id=match.id, subject="s", body="b", status="draft")
    db_session.add(email)
    db_session.flush()

    out = submit_feedback(
        FeedbackCreate(match_id=match.id, email_id=email.id, rating=-1),
        db=db_session,
    )
    assert out.email_id == email.id
    assert out.rating == -1


# ---------------------------------------------------------------------------
# Buyer-facing email (Layer 3)
# ---------------------------------------------------------------------------


def test_buyer_email_recommends_top_matches_real_db(db_session) -> None:
    tender = _make_tender()
    top = _make_company_profile(name="Top Supplier")
    second = _make_company_profile(name="Second Supplier")
    db_session.add_all([tender, top, second])
    db_session.flush()

    db_session.add_all([
        _make_match(tender.id, top.id, final_score=0.92),
        _make_match(tender.id, second.id, final_score=0.61),
    ])
    db_session.flush()

    out = generate_buyer_email(tender.id, db=db_session, top_n=3)

    assert out.recipient_type == "buyer"
    suppliers = out.evidence["recommended_suppliers"]
    assert [s["name"] for s in suppliers] == ["Top Supplier", "Second Supplier"]
    assert out.company.name == "Top Supplier"  # anchored to the top match
    assert "Top Supplier" in out.body
    assert out.tender.ted_notice_id == tender.ted_notice_id

    stored = db_session.query(Email).filter_by(tender_id=tender.id).all()
    assert len(stored) == 1
    assert stored[0].recipient_type == "buyer"


def test_buyer_email_409_when_no_matches_real_db(db_session) -> None:
    tender = _make_tender(ted_notice_id="NO-MATCH-1")
    db_session.add(tender)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        generate_buyer_email(tender.id, db=db_session)
    assert exc_info.value.status_code == 409


def test_buyer_email_excludes_disqualified_real_db(db_session) -> None:
    tender = _make_tender()
    good = _make_company_profile(name="Eligible Co")
    bad = _make_company_profile(name="Disqualified Co")
    db_session.add_all([tender, good, bad])
    db_session.flush()
    db_session.add_all([
        _make_match(tender.id, good.id, final_score=0.5),
        _make_match(tender.id, bad.id, final_score=0.99, is_disqualified=True),
    ])
    db_session.flush()

    out = generate_buyer_email(tender.id, db=db_session)
    names = [s["name"] for s in out.evidence["recommended_suppliers"]]
    assert names == ["Eligible Co"]  # disqualified excluded despite higher score
