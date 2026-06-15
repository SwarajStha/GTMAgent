"""Tests for tender API response shaping."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.v1.tenders import get_tender, list_tenders
from app.main import app


def _tender(**overrides: object) -> SimpleNamespace:
    base = {
        "id": 1,
        "ted_notice_id": "326612-2026",
        "title": "Construction technology platform",
        "buyer_name": "City Buyer",
        "buyer_country": "DE",
        "cpv_codes": ["45000000", "72000000"],
        "deadline": datetime(2026, 7, 1, tzinfo=UTC),
        "budget_eur": 1_500_000.0,
        "currency": "EUR",
        "status": "active",
        "document_url": "https://ted.europa.eu/notice/326612-2026",
        "is_restricted": False,
        "raw_json": {"publication-number": "326612-2026"},
        "ingested_at": datetime(2026, 6, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 2, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_list_tenders_returns_paged_items() -> None:
    db = MagicMock()
    db.scalar.return_value = 1
    db.scalars.return_value.all.return_value = [_tender()]

    response = list_tenders(db=db)

    assert response.total == 1
    assert response.limit == 50
    assert response.offset == 0
    assert response.items[0].ted_notice_id == "326612-2026"
    assert response.items[0].cpv_codes == ["45000000", "72000000"]


def test_list_tenders_endpoint_returns_json() -> None:
    db = MagicMock()
    db.scalar.return_value = 1
    db.scalars.return_value.all.return_value = [_tender()]
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/tenders/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["ted_notice_id"] == "326612-2026"


def test_get_tender_returns_detail() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = _tender()

    response = get_tender("326612-2026", db=db)

    assert response.id == 1
    assert response.raw_json == {"publication-number": "326612-2026"}


def test_get_tender_raises_404_when_missing() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        get_tender("missing", db=db)

    assert exc_info.value.status_code == 404
