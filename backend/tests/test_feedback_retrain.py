"""DB-backed tests for the feedback → LR retraining loop (Step 5 / G8).

Exercises the real `gtm_test` schema: `FeedbackRetrainer` over `feedback.features`
snapshots, and the feedback endpoint snapshotting a match's feature vector.
"""
from __future__ import annotations

from app.api.v1.feedback import FeedbackCreate, _match_features, submit_feedback
from app.db.models import CompanyProfile, Feedback, Match, Tender
from app.matching.features import FEATURE_NAMES
from app.matching.lr_weights import FeedbackRetrainer, LogisticRegressionScorer


def _feat(**overrides: float) -> dict[str, float]:
    base = {name: 0.5 for name in FEATURE_NAMES}
    base.update(overrides)
    return base


def _add_feedback(db, rating: int, features: dict | None) -> None:
    db.add(Feedback(rating=rating, features=features))


# ── FeedbackRetrainer ───────────────────────────────────────────────────────


def test_retrain_insufficient_too_few(db_session, tmp_path) -> None:
    _add_feedback(db_session, 1, _feat(cpv_4digit_score=1.0))
    _add_feedback(db_session, -1, _feat(cpv_4digit_score=0.0))
    db_session.flush()
    out = tmp_path / "fb.json"
    result = FeedbackRetrainer(min_samples=10, out_path=out).retrain(db_session)
    assert result["status"] == "insufficient"
    assert result["n_samples"] == 2
    assert not out.exists()


def test_retrain_insufficient_single_class(db_session, tmp_path) -> None:
    for _ in range(12):
        _add_feedback(db_session, 1, _feat())  # all positive
    db_session.flush()
    out = tmp_path / "fb.json"
    result = FeedbackRetrainer(min_samples=5, out_path=out).retrain(db_session)
    assert result["status"] == "insufficient"
    assert result["n_pos"] == 12 and result["n_neg"] == 0
    assert not out.exists()


def test_retrain_ignores_feedback_without_snapshot(db_session, tmp_path) -> None:
    _add_feedback(db_session, 1, None)   # feedback on a legacy/disqualified match
    _add_feedback(db_session, -1, None)
    db_session.flush()
    result = FeedbackRetrainer(min_samples=2, out_path=tmp_path / "fb.json").retrain(db_session)
    assert result["status"] == "insufficient"
    assert result["n_samples"] == 0


def test_retrain_writes_params_and_learns(db_session, tmp_path) -> None:
    # Positives prefer high cpv_4digit + semantic; negatives the opposite.
    for _ in range(8):
        _add_feedback(db_session, 1, _feat(cpv_4digit_score=1.0, semantic_score=0.9))
    for _ in range(8):
        _add_feedback(db_session, -1, _feat(cpv_4digit_score=0.0, semantic_score=0.1))
    db_session.flush()

    out = tmp_path / "model_params_feedback.json"
    result = FeedbackRetrainer(min_samples=5, out_path=out).retrain(db_session)
    assert result["status"] == "retrained"
    assert (result["n_samples"], result["n_pos"], result["n_neg"]) == (16, 8, 8)
    assert out.exists()

    scorer = LogisticRegressionScorer.from_json(out)
    assert scorer is not None
    high = scorer.score(_feat(cpv_4digit_score=1.0, semantic_score=0.9))
    low = scorer.score(_feat(cpv_4digit_score=0.0, semantic_score=0.1))
    assert high > low  # the model learned the feedback signal


# ── feedback endpoint feature snapshot ──────────────────────────────────────


def test_match_features_none_when_columns_unset() -> None:
    from types import SimpleNamespace

    legacy = SimpleNamespace(**{name: None for name in FEATURE_NAMES})
    assert _match_features(legacy) is None


def test_submit_feedback_snapshots_match_features(db_session) -> None:
    tender = Tender(ted_notice_id="T-FB-1", raw_json={"publication-number": "T-FB-1"})
    db_session.add(tender)
    db_session.flush()
    profile = CompanyProfile(name="Bau GmbH", country="DE", capabilities={})
    db_session.add(profile)
    db_session.flush()
    match = Match(
        tender_id=tender.id,
        company_id=profile.id,
        semantic_score=0.4,
        budget_score=0.5,
        location_score=1.0,
        qualification_score=1.0,
        final_score=0.3,
        cpv_4digit_score=1.0,
        cpv_2digit_score=1.0,
        nuts_exact_score=0.5,
        nuts_country_score=0.5,
        value_score=0.5,
        value_in_range_score=0.5,
        country_match_score=1.0,
        company_size_score=0.15,
        competition_score=0.5,
    )
    db_session.add(match)
    db_session.flush()

    submit_feedback(FeedbackCreate(match_id=match.id, rating=1), db=db_session)

    fb = db_session.query(Feedback).filter_by(match_id=match.id).one()
    assert fb.features is not None
    assert fb.features["cpv_4digit_score"] == 1.0
    assert set(fb.features) == set(FEATURE_NAMES)
