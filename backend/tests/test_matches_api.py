"""Tests for match API response shaping."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.v1.matches import MatchWeightsIn, get_match, list_matches, run_matching
from app.main import app

MATCH_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
EMAIL_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _tender(**overrides: object) -> SimpleNamespace:
    base = {
        "id": 1,
        "ted_notice_id": "326612-2026",
        "title": "Construction technology platform",
        "buyer_name": "City Buyer",
        "buyer_country": "DE",
        "deadline": datetime(2026, 7, 1, tzinfo=UTC),
        "budget_eur": 1_500_000.0,
        "status": "active",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _company_profile(**overrides: object) -> SimpleNamespace:
    base = {
        "id": COMPANY_ID,
        "name": "BuildFlow Systems",
        "country": "DE",
        "website": "https://buildflow.example",
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
        "cpv_4digit_score": 1.0,
        "cpv_2digit_score": 1.0,
        "nuts_exact_score": 0.5,
        "nuts_country_score": 0.5,
        "value_score": 0.88,
        "value_in_range_score": 1.0,
        "country_match_score": 0.97,
        "company_size_score": 0.6,
        "competition_score": 0.5,
        "final_score": 0.93,
        "weights": {"semantic": 0.5, "budget": 0.2},
        "explanation": "Strong product overlap with buyer needs.",
        "is_disqualified": False,
        "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 2, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _email(**overrides: object) -> SimpleNamespace:
    base = {
        "id": EMAIL_ID,
        "subject": "Munich BIM permitting tender",
        "status": "draft",
        "sent_at": None,
        "created_at": datetime(2026, 6, 3, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 3, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_list_matches_returns_paged_items() -> None:
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.return_value.all.return_value = [(_match(), _tender(), _company_profile())]

    response = list_matches(db=db)

    assert response.total == 1
    assert response.items[0].id == MATCH_ID
    assert response.items[0].final_score == 0.93
    assert response.items[0].tender.ted_notice_id == "326612-2026"
    assert response.items[0].company.name == "BuildFlow Systems"


def test_list_matches_endpoint_returns_json() -> None:
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.return_value.all.return_value = [(_match(), _tender(), _company_profile())]
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/matches/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(MATCH_ID)
    assert body["items"][0]["company"]["name"] == "BuildFlow Systems"


def test_get_match_returns_detail_with_email_summaries() -> None:
    db = MagicMock()
    db.execute.return_value.first.return_value = (_match(), _tender(), _company_profile())
    db.scalars.return_value.all.return_value = [_email()]

    response = get_match(MATCH_ID, db=db)

    assert response.id == MATCH_ID
    assert response.emails[0].id == EMAIL_ID
    assert response.emails[0].subject == "Munich BIM permitting tender"


def test_get_match_raises_404_when_missing() -> None:
    db = MagicMock()
    db.execute.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        get_match(MATCH_ID, db=db)

    assert exc_info.value.status_code == 404


def test_run_matching_404_when_tender_missing() -> None:
    db = MagicMock()
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        run_matching(999, db=db)

    assert exc_info.value.status_code == 404


def test_run_matching_delegates_to_pipeline_and_shapes_result() -> None:
    db = MagicMock()
    db.get.return_value = _tender()
    canned = [
        {"company_id": str(COMPANY_ID), "company_name": "Floor Pros", "final_score": 0.9},
    ]

    with patch("app.matching.pipeline.MatchingPipeline") as pipeline_cls:
        pipeline_cls.return_value.run.return_value = canned
        response = run_matching(1, db=db, top_n=3)

    assert response.tender_id == 1
    assert response.count == 1
    assert response.mode == "lr"
    assert response.matches[0]["company_name"] == "Floor Pros"
    pipeline_cls.return_value.run.assert_called_once_with(1, session=db, top_n=3)


def test_run_matching_with_weights_uses_weighted_mode() -> None:
    # G16: posting operator weights re-ranks in legacy weighted mode (use_lr=False)
    # with those weights, instead of the trained LR.
    db = MagicMock()
    db.get.return_value = _tender()
    weights = MatchWeightsIn(semantic=0.5, budget=0.2, location=0.2, qualification=0.1)

    with patch("app.matching.pipeline.MatchingPipeline") as pipeline_cls:
        pipeline_cls.return_value.run.return_value = []
        response = run_matching(1, db=db, weights=weights)

    expected = {"semantic": 0.5, "budget": 0.2, "location": 0.2, "qualification": 0.1}
    assert response.mode == "weighted"
    assert response.weights == expected
    pipeline_cls.assert_called_once_with(weights=expected, use_lr=False)


def test_run_matching_rejects_zero_weights() -> None:
    db = MagicMock()
    db.get.return_value = _tender()
    weights = MatchWeightsIn(semantic=0.0, budget=0.0, location=0.0, qualification=0.0)

    with pytest.raises(HTTPException) as exc_info:
        run_matching(1, db=db, weights=weights)

    assert exc_info.value.status_code == 422
