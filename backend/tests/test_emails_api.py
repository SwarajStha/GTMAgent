"""Tests for email generation and retrieval endpoints."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.v1.emails import generate_email, get_email
from app.db.models import CompanyProfile, Document, Match, Tender
from app.main import app

MATCH_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
EMAIL_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
DOCUMENT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _tender(**overrides: object) -> SimpleNamespace:
    base = {
        "id": 1,
        "ted_notice_id": "326612-2026",
        "title": "Digital permitting platform",
        "buyer_name": "City Buyer",
        "buyer_country": "DE",
        "deadline": datetime(2026, 7, 1, tzinfo=UTC),
        "budget_eur": 1_500_000.0,
        "cpv_codes": ["72000000"],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _company_profile(**overrides: object) -> SimpleNamespace:
    base = {
        "id": COMPANY_ID,
        "name": "BuildFlow Systems",
        "country": "DE",
        "website": "https://buildflow.example",
        "capabilities": {"workflow": ["permitting", "BIM"]},
        "certifications": {"security": ["ISO 27001"]},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _match(**overrides: object) -> SimpleNamespace:
    base = {
        "id": MATCH_ID,
        "tender_id": 1,
        "company_id": COMPANY_ID,
        "semantic_score": 0.94,
        "budget_score": 0.88,
        "location_score": 0.97,
        "qualification_score": 0.91,
        "final_score": 0.93,
        "explanation": "Strong product overlap with buyer needs.",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _document(**overrides: object) -> SimpleNamespace:
    # Mirror the real `Document` columns (no `filename` / `text_content` /
    # `created_at` exist on the model — those names previously masked a bug
    # that only surfaced against a real schema; see test_generate_email_writes_real_draft).
    base = {
        "id": DOCUMENT_ID,
        "tender_id": 1,
        "source_url": "https://ted.europa.eu/dossier/source.pdf",
        "storage_path": "/storage/dossiers/326612-2026/notice.pdf",
        "extracted_text": "Tender asks for digital permitting and BIM coordination.",
        "downloaded_at": datetime(2026, 6, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _email(**overrides: object) -> SimpleNamespace:
    base = {
        "id": EMAIL_ID,
        "match_id": MATCH_ID,
        "subject": "Digital permitting platform - opportunity for BuildFlow Systems",
        "body": "Hi BuildFlow Systems team,\n\nWe found a public tender.",
        "evidence": {"match_id": str(MATCH_ID)},
        "status": "draft",
        "sent_at": None,
        "created_at": datetime(2026, 6, 3, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 3, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _assign_email_defaults(email: object) -> None:
    email.id = EMAIL_ID
    email.sent_at = None
    email.created_at = datetime(2026, 6, 3, tzinfo=UTC)
    email.updated_at = datetime(2026, 6, 3, tzinfo=UTC)


def test_generate_email_creates_draft() -> None:
    db = MagicMock()
    db.execute.return_value.tuples.return_value.first.return_value = (
        _match(),
        _tender(),
        _company_profile(),
    )
    db.scalars.return_value.all.return_value = [_document()]
    db.refresh.side_effect = _assign_email_defaults

    response = generate_email(MATCH_ID, db=db)

    assert response.id == EMAIL_ID
    assert response.match_id == MATCH_ID
    assert response.status == "draft"
    assert response.company.name == "BuildFlow Systems"
    assert response.tender.ted_notice_id == "326612-2026"
    assert response.evidence is not None
    assert response.evidence["document_snippets"][0]["filename"] == "notice.pdf"
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_generate_email_endpoint_returns_json() -> None:
    db = MagicMock()
    db.execute.return_value.tuples.return_value.first.return_value = (
        _match(),
        _tender(),
        _company_profile(),
    )
    db.scalars.return_value.all.return_value = [_document()]
    db.refresh.side_effect = _assign_email_defaults
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            response = client.post(f"/api/v1/emails/{MATCH_ID}/generate")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(EMAIL_ID)
    assert body["company"]["name"] == "BuildFlow Systems"


def test_generate_email_raises_404_when_match_missing() -> None:
    db = MagicMock()
    db.execute.return_value.tuples.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        generate_email(MATCH_ID, db=db)

    assert exc_info.value.status_code == 404


def test_get_email_returns_detail() -> None:
    db = MagicMock()
    db.execute.return_value.first.return_value = (_email(), _tender(), _company_profile())

    response = get_email(EMAIL_ID, db=db)

    assert response.id == EMAIL_ID
    assert response.match_id == MATCH_ID
    assert response.tender.title == "Digital permitting platform"
    assert response.company.name == "BuildFlow Systems"


def test_get_email_raises_404_when_missing() -> None:
    db = MagicMock()
    db.execute.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        get_email(EMAIL_ID, db=db)

    assert exc_info.value.status_code == 404


def test_generate_email_writes_real_draft(db_session) -> None:
    """End-to-end against a real Postgres schema.

    The mock-based tests above pass even when the handler references columns
    that don't exist on the ORM model (e.g. the old `Document.created_at` /
    `.text_content` / `.filename`). This exercises the actual query + evidence
    collection against `app.db.models` so that kind of schema drift fails loudly.
    """
    tender = Tender(
        ted_notice_id="326612-2026",
        title="Digital permitting platform",
        buyer_name="City Buyer",
        buyer_country="DE",
        cpv_codes=["72000000"],
        budget_eur=1_500_000.0,
        raw_json={"source": "test"},
    )
    company = CompanyProfile(name="BuildFlow Systems", country="DE")
    db_session.add_all([tender, company])
    db_session.flush()

    match = Match(
        tender_id=tender.id,
        company_id=company.id,
        semantic_score=0.94,
        budget_score=0.88,
        location_score=0.97,
        qualification_score=0.91,
        final_score=0.93,
        explanation="Strong product overlap with buyer needs.",
    )
    document = Document(
        tender_id=tender.id,
        source_url="https://ted.europa.eu/dossier/source.pdf",
        storage_path="/storage/dossiers/326612-2026/notice.pdf",
        extracted_text="Tender asks for digital permitting and BIM coordination.",
        downloaded_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    db_session.add_all([match, document])
    db_session.flush()

    response = generate_email(match.id, db=db_session)

    assert response.match_id == match.id
    assert response.status == "draft"
    assert response.company.name == "BuildFlow Systems"
    assert response.tender.ted_notice_id == "326612-2026"
    assert response.evidence is not None
    snippets = response.evidence["document_snippets"]
    assert snippets[0]["filename"] == "notice.pdf"
    assert "digital permitting" in snippets[0]["snippet"]
