"""Tests for feedback submission endpoint."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.v1.feedback import FeedbackCreate, submit_feedback
from app.main import app

MATCH_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_MATCH_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
EMAIL_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
FEEDBACK_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _assign_feedback_defaults(feedback: object) -> None:
    feedback.id = FEEDBACK_ID
    feedback.created_at = datetime(2026, 6, 4, tzinfo=UTC)
    feedback.updated_at = datetime(2026, 6, 4, tzinfo=UTC)


def test_submit_feedback_creates_match_feedback() -> None:
    db = MagicMock()
    db.scalar.return_value = True
    db.refresh.side_effect = _assign_feedback_defaults
    payload = FeedbackCreate(match_id=MATCH_ID, rating=1, comment="Good fit")

    response = submit_feedback(payload, db=db)

    assert response.id == FEEDBACK_ID
    assert response.match_id == MATCH_ID
    assert response.email_id is None
    assert response.rating == 1
    assert response.comment == "Good fit"
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_submit_feedback_endpoint_returns_json() -> None:
    db = MagicMock()
    db.scalar.return_value = True
    db.refresh.side_effect = _assign_feedback_defaults
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/feedback/",
                json={"match_id": str(MATCH_ID), "rating": -1, "comment": "Too broad"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(FEEDBACK_ID)
    assert body["rating"] == -1


def test_submit_feedback_accepts_email_for_same_match() -> None:
    db = MagicMock()
    db.scalar.side_effect = [True, MATCH_ID]
    db.refresh.side_effect = _assign_feedback_defaults
    payload = FeedbackCreate(match_id=MATCH_ID, email_id=EMAIL_ID, rating=1)

    response = submit_feedback(payload, db=db)

    assert response.email_id == EMAIL_ID


def test_submit_feedback_raises_404_when_match_missing() -> None:
    db = MagicMock()
    db.scalar.return_value = False
    payload = FeedbackCreate(match_id=MATCH_ID, rating=1)

    with pytest.raises(HTTPException) as exc_info:
        submit_feedback(payload, db=db)

    assert exc_info.value.status_code == 404


def test_submit_feedback_raises_404_when_email_missing() -> None:
    db = MagicMock()
    db.scalar.side_effect = [True, None]
    payload = FeedbackCreate(match_id=MATCH_ID, email_id=EMAIL_ID, rating=1)

    with pytest.raises(HTTPException) as exc_info:
        submit_feedback(payload, db=db)

    assert exc_info.value.status_code == 404


def test_submit_feedback_rejects_email_for_other_match() -> None:
    db = MagicMock()
    db.scalar.side_effect = [True, OTHER_MATCH_ID]
    payload = FeedbackCreate(match_id=MATCH_ID, email_id=EMAIL_ID, rating=1)

    with pytest.raises(HTTPException) as exc_info:
        submit_feedback(payload, db=db)

    assert exc_info.value.status_code == 400


def test_submit_feedback_rejects_zero_rating() -> None:
    db = MagicMock()
    payload = FeedbackCreate(match_id=MATCH_ID, rating=0)

    with pytest.raises(HTTPException) as exc_info:
        submit_feedback(payload, db=db)

    assert exc_info.value.status_code == 422
