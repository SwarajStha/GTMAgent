"""Tests for award and canonical-company API response shaping."""
from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.v1.awards import get_award, list_awards
from app.api.v1.companies import get_company, list_companies
from app.main import app


def _award(**overrides: object) -> SimpleNamespace:
    base = {
        "id": 1,
        "ted_notice_id": "123456-2026",
        "cpv_code": "45000000",
        "buyer_name": "City Buyer",
        "buyer_country": "DE",
        "winner_raw_name": "Build GmbH",
        "winner_canonical_id": 7,
        "contract_value_eur": 750_000.0,
        "award_date": date(2026, 5, 12),
        "n_offers_received": 4,
        "raw_json": {"publication-number": "123456-2026"},
        "ingested_at": datetime(2026, 6, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _company(**overrides: object) -> SimpleNamespace:
    base = {
        "id": 7,
        "canonical_name": "Build GmbH",
        "resolution_key": "build",
        "aliases": ["Build GmbH"],
        "country": "DE",
        "created_at": datetime(2026, 5, 17, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_list_awards_returns_paged_items() -> None:
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.return_value.all.return_value = [(_award(), "Build GmbH")]

    response = list_awards(db=db)

    assert response.total == 1
    assert response.items[0].ted_notice_id == "123456-2026"
    assert response.items[0].winner_canonical_name == "Build GmbH"


def test_list_awards_endpoint_returns_json() -> None:
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.return_value.all.return_value = [(_award(), "Build GmbH")]
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/awards/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["winner_canonical_name"] == "Build GmbH"


def test_get_award_returns_detail() -> None:
    db = MagicMock()
    db.execute.return_value.first.return_value = (_award(), "Build GmbH")

    response = get_award(1, db=db)

    assert response.id == 1
    assert response.raw_json == {"publication-number": "123456-2026"}


def test_get_award_raises_404_when_missing() -> None:
    db = MagicMock()
    db.execute.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        get_award(999, db=db)

    assert exc_info.value.status_code == 404


def test_list_companies_returns_rollups() -> None:
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.return_value.all.return_value = [(_company(), 3, 2_500_000.0, date(2026, 5, 12))]

    response = list_companies(db=db)

    assert response.total == 1
    assert response.items[0].canonical_name == "Build GmbH"
    assert response.items[0].award_count == 3
    assert response.items[0].total_contract_value_eur == 2_500_000.0


def test_get_company_returns_recent_awards() -> None:
    db = MagicMock()
    company_result = MagicMock()
    company_result.first.return_value = (_company(), 1, 750_000.0, date(2026, 5, 12))
    awards_result = MagicMock()
    awards_result.all.return_value = [(_award(), "Build GmbH")]
    db.execute.side_effect = [company_result, awards_result]

    response = get_company(7, db=db)

    assert response.id == 7
    assert response.recent_awards[0].winner_canonical_name == "Build GmbH"


def test_get_company_raises_404_when_missing() -> None:
    db = MagicMock()
    db.execute.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        get_company(999, db=db)

    assert exc_info.value.status_code == 404
