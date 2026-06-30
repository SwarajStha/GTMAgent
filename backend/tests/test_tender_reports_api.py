"""Tests for the saved-agent-analysis endpoints (tender_reports, migration 0015)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.db.models import CompanyProfile, Match, Tender
from app.main import app


def _seed_tender_with_match(db) -> tuple[Tender, Match, CompanyProfile]:
    tender = Tender(
        ted_notice_id="REP-1",
        title="Report tender",
        cpv_codes=["45000000"],
        raw_json={"publication-number": "REP-1"},
    )
    db.add(tender)
    db.flush()
    company = CompanyProfile(name="Acme Build", country="DEU")
    db.add(company)
    db.flush()
    match = Match(
        tender_id=tender.id,
        company_id=company.id,
        semantic_score=0.8,
        budget_score=0.5,
        location_score=1.0,
        qualification_score=0.9,
        final_score=0.7,
        is_disqualified=False,
    )
    db.add(match)
    db.flush()
    return tender, match, company


def test_save_and_list_tender_report(db_session) -> None:
    tender, match, company = _seed_tender_with_match(db_session)

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            saved = client.post(
                f"/api/v1/tenders/{tender.id}/reports",
                json={"narrative": "Top supplier is Acme.", "goal": "find suppliers"},
            )
            assert saved.status_code == 200
            body = saved.json()
            assert body["tender_id"] == tender.id
            assert body["narrative"] == "Top supplier is Acme."
            # Supplier snapshot is built server-side from the tender's matches.
            assert body["suppliers"][0]["company_name"] == "Acme Build"
            assert body["suppliers"][0]["match_id"] == str(match.id)

            listed = client.get(f"/api/v1/tenders/{tender.id}/reports")
            assert listed.status_code == 200
            assert len(listed.json()) == 1
            assert listed.json()[0]["narrative"] == "Top supplier is Acme."
    finally:
        app.dependency_overrides.clear()


def test_save_report_keeps_history(db_session) -> None:
    """Many reports per tender — each save appends a new row."""
    tender, _match, _company = _seed_tender_with_match(db_session)

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            client.post(f"/api/v1/tenders/{tender.id}/reports", json={"narrative": "first"})
            client.post(f"/api/v1/tenders/{tender.id}/reports", json={"narrative": "second"})
            listed = client.get(f"/api/v1/tenders/{tender.id}/reports").json()
            assert len(listed) == 2
            # Both saved (the list is ordered created_at desc — newest first in
            # production, where each request is its own transaction; under the
            # test's single-transaction savepoint now() ties, so assert membership).
            assert {r["narrative"] for r in listed} == {"first", "second"}
    finally:
        app.dependency_overrides.clear()


def test_save_report_unknown_tender_404(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            r = client.post("/api/v1/tenders/999999/reports", json={"narrative": "x"})
            assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()
