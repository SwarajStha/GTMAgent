"""DB-backed tests for the Understanding-layer service + extract endpoint."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.v1.tenders import extract_tender_profile
from app.db.models import Tender
from app.understanding.extractor import FieldExtractor
from app.understanding.service import (
    META_KEY,
    build_tender_text,
    extract_and_store_tender_profile,
)


def _tender(**kw: object) -> Tender:
    base = {
        "ted_notice_id": "T-UND-1",
        "title": "Clinic construction works",
        "description": "Build a 200-bed clinic including HVAC and electrical works.",
        "buyer_country": "DE",
        "cpv_codes": ["45215130"],
        "budget_eur": 1_200_000.0,
        "deadline": datetime(2026, 9, 1, tzinfo=UTC),
        "raw_json": {"publication-number": "T-UND-1"},
    }
    base.update(kw)
    return Tender(**base)


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self.messages = SimpleNamespace(
            create=lambda **_k: SimpleNamespace(
                content=[SimpleNamespace(type="text", text=json.dumps(payload))]
            )
        )


def test_build_tender_text_concatenates_fields(db_session) -> None:
    tender = _tender()
    db_session.add(tender)
    db_session.flush()
    text = build_tender_text(db_session, tender)
    assert "Clinic construction works" in text
    assert "200-bed clinic" in text
    assert "45215130" in text


def test_extract_and_store_offline_persists_fallback_profile(db_session) -> None:
    tender = _tender()
    db_session.add(tender)
    db_session.flush()

    stored = extract_and_store_tender_profile(db_session, tender)

    assert stored["cpv_code"] == "45215130"
    assert stored[META_KEY]["source"] == "fallback"  # offline → deterministic
    assert stored[META_KEY]["validation_ok"] is True
    # Round-trips to the column.
    refreshed = db_session.get(Tender, tender.id)
    assert refreshed.tender_profile[META_KEY]["source"] == "fallback"


def test_extract_and_store_claude_path_captures_certs(db_session) -> None:
    tender = _tender()
    db_session.add(tender)
    db_session.flush()

    extractor = FieldExtractor(
        client=_FakeClient(
            {
                "summary": "Clinic build.",
                "required_certifications": ["ISO 9001"],
                "required_capabilities": ["HVAC"],
                "keywords": ["clinic"],
                "language": "de",
            }
        )
    )
    stored = extract_and_store_tender_profile(db_session, tender, extractor=extractor)

    assert stored["required_certifications"] == ["ISO 9001"]
    assert stored[META_KEY]["source"] == "claude"


def test_extract_endpoint_returns_profile(db_session) -> None:
    tender = _tender(ted_notice_id="T-UND-2")
    db_session.add(tender)
    db_session.flush()

    out = extract_tender_profile(str(tender.id), db=db_session)

    assert out.tender_id == tender.id
    assert out.profile["cpv_code"] == "45215130"
    assert META_KEY in out.profile
