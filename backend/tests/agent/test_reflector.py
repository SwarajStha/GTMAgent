"""Tests for the reflection loop wired to behaviour (G9).

DB-backed (real `gtm_test` schema via `db_session`). Stays sklearn-free: the
retrain action is either driven to the `insufficient` guard (no sklearn import)
or monkeypatched, so CI (lean deps) is unaffected. The Claude narrative path is
covered with an injected fake client; everything else runs offline.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.agent.reflector as reflector
from app.agent.reflector import Reflector
from app.db.models import AgentRun, CompanyProfile, Feedback, Match, Reflection, Tender
from app.matching.features import FEATURE_NAMES


def _feat(**overrides: float) -> dict[str, float]:
    base = {name: 0.5 for name in FEATURE_NAMES}
    base.update(overrides)
    return base


def _tender(db, notice: str, cpv: str) -> Tender:
    t = Tender(ted_notice_id=notice, cpv_codes=[cpv], raw_json={"publication-number": notice})
    db.add(t)
    db.flush()
    return t


def _match(db, tender: Tender) -> Match:
    profile = CompanyProfile(name=f"Co {tender.ted_notice_id}", country="DE", capabilities={})
    db.add(profile)
    db.flush()
    m = Match(tender_id=tender.id, company_id=profile.id, final_score=0.5)
    db.add(m)
    db.flush()
    return m


# ── metrics ───────────────────────────────────────────────────────────────────


def test_compute_metrics_counts(db_session) -> None:
    db_session.add_all([AgentRun(goal="g1"), AgentRun(goal="g2")])
    db_session.add_all(
        [
            Feedback(rating=1, features=_feat()),
            Feedback(rating=1, features=_feat()),
            Feedback(rating=-1, features=None),  # not trainable
        ]
    )
    db_session.flush()

    metrics = Reflector().compute_metrics(db_session)
    assert metrics["agent_runs_total"] == 2
    assert metrics["feedback_total"] == 3
    assert metrics["feedback_pos"] == 2
    assert metrics["feedback_neg"] == 1
    assert metrics["feedback_trainable"] == 2
    assert metrics["avg_rating"] == round((1 + 1 - 1) / 3, 3)
    assert set(metrics["recent_run_goals"]) == {"g1", "g2"}


def test_cpv_recommendations_flags_negative_division(db_session) -> None:
    # Three "45" (construction) tenders, each down-voted → review.
    for i in range(3):
        t = _tender(db_session, f"T-45-{i}", "45233223")
        m = _match(db_session, t)
        db_session.add(Feedback(match_id=m.id, rating=-1, features=None))
    db_session.flush()

    recs = {r["cpv_division"]: r for r in Reflector()._cpv_recommendations(db_session)}
    assert "45" in recs
    assert recs["45"]["tender_volume"] == 3
    assert recs["45"]["feedback_count"] == 3
    assert recs["45"]["avg_rating"] == -1.0
    assert recs["45"]["recommendation"] == "review"


def test_cpv_recommendations_below_volume_threshold_is_silent(db_session) -> None:
    # A single tender in a division: too little volume to opine on.
    t = _tender(db_session, "T-72-1", "72000000")
    m = _match(db_session, t)
    db_session.add(Feedback(match_id=m.id, rating=-1, features=None))
    db_session.flush()

    recs = {r["cpv_division"] for r in Reflector()._cpv_recommendations(db_session)}
    assert "72" not in recs


# ── reflect() orchestration ─────────────────────────────────────────────────────


def test_reflect_persists_and_records_insufficient_retrain(db_session) -> None:
    db_session.add(Feedback(rating=1, features=_feat()))
    db_session.add(Feedback(rating=-1, features=_feat()))
    db_session.flush()

    result = Reflector(min_samples=10).reflect(session=db_session)

    # Persisted exactly one reflection row.
    rows = db_session.query(Reflection).all()
    assert len(rows) == 1
    assert rows[0].narrative

    # Two labelled samples < min_samples → retrainer reports insufficient (no sklearn).
    assert result["actions"]["retrain"]["status"] == "insufficient"
    assert result["actions"]["cpv_applied"] is False
    assert result["actions"]["narrative_source"] == "deterministic"
    assert "Reflection summary" in result["narrative"]


def test_reflect_act_false_skips_retrain(db_session) -> None:
    result = Reflector().reflect(session=db_session, act=False)
    assert "retrain" not in result["actions"]
    assert db_session.query(Reflection).count() == 1


def test_reflect_records_retrain_outcome(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock the retrainer so we assert the wiring (action recorded + narrated)
    # without needing sklearn / enough real feedback.
    fake = {"status": "retrained", "n_samples": 16, "n_pos": 8, "n_neg": 8}
    monkeypatch.setattr(reflector.FeedbackRetrainer, "retrain", lambda self, session: fake)

    result = Reflector().reflect(session=db_session)
    assert result["actions"]["retrain"] == fake
    assert "served model updated" in result["narrative"]


def test_reflect_retrain_error_is_contained(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self, session):
        raise RuntimeError("no sklearn")

    monkeypatch.setattr(reflector.FeedbackRetrainer, "retrain", boom)
    result = Reflector().reflect(session=db_session)
    assert result["actions"]["retrain"]["status"] == "error"
    assert db_session.query(Reflection).count() == 1  # cycle still persisted


def test_reflect_claude_narrative_with_injected_client(db_session) -> None:
    class _FakeMessages:
        def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(text="Claude says hi")])

    class _FakeClient:
        messages = _FakeMessages()

    result = Reflector(client=_FakeClient()).reflect(session=db_session)
    assert result["narrative"] == "Claude says hi"
    assert result["actions"]["narrative_source"] == "claude"


def test_reflect_claude_failure_falls_back_to_deterministic(db_session) -> None:
    class _BoomMessages:
        def create(self, **kwargs):
            raise RuntimeError("api down")

    class _BoomClient:
        messages = _BoomMessages()

    result = Reflector(client=_BoomClient()).reflect(session=db_session)
    assert result["actions"]["narrative_source"] == "deterministic"
    assert "Reflection summary" in result["narrative"]
