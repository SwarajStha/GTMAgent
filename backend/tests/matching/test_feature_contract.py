"""Train/serve contract tests (G20) — keep the served model and the served
features from silently drifting apart.

`app/matching/features.py` computes the feature dict; `exports/model_params.json`
holds the coefficients the offline v5 trainer (`exports_ml_pipeline.py`) produced.
The scorer in `lr_weights.py` pairs them **by name**, and `features.py` documents
that `FEATURE_NAMES` order "is load-bearing: it must match
model_params.json['feature_names']". Nothing enforced that — so a feature added,
removed, or reordered in one place but not the other would ship a silently-wrong
ranking. These tests are the enforcement, and they are ML-dep-free (pure JSON +
the pure-python scorer), so they run in CI where `exports/model_params.json` is
committed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.matching import features
from app.matching.lr_weights import (
    DEFAULT_PARAMS_PATH,
    FEEDBACK_PARAMS_PATH,
    LogisticRegressionScorer,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_committed_model_params_exists() -> None:
    # The whole contract is moot if the artifact the app loads isn't in the repo.
    assert DEFAULT_PARAMS_PATH.exists(), (
        f"{DEFAULT_PARAMS_PATH} is missing — the in-app matcher has no LR to load; "
        "regenerate it with exports_ml_pipeline.py."
    )


def test_feature_names_match_committed_model_exactly() -> None:
    """The load-bearing invariant: code order == artifact order, element for element."""
    params = _load(DEFAULT_PARAMS_PATH)
    assert params["feature_names"] == features.FEATURE_NAMES, (
        "FEATURE_NAMES in app/matching/features.py has drifted from "
        "exports/model_params.json — re-port the feature change into features.py "
        "and regenerate model_params.json so they match."
    )


def test_committed_model_param_arrays_align_with_feature_count() -> None:
    params = _load(DEFAULT_PARAMS_PATH)
    n = len(features.FEATURE_NAMES)
    assert len(params["coefficients"]) == n
    assert len(params["scaler_mean"]) == n
    assert len(params["scaler_scale"]) == n


def test_compute_features_produces_exactly_the_scorer_keys() -> None:
    """Every name the scorer looks up must be produced by compute_features, and no
    extra feature may be produced that the model never learned a weight for."""
    caps = {
        "cpv_codes": ["45233000"],
        "nuts_codes": ["DE21"],
        "deal_size_eur": {"min": 30_000, "max": 500_000, "median": 100_000},
        "regions": ["DEU"],
        "award_count": 12,
    }
    computed = features.compute_features(
        semantic_score=0.7,
        tender_cpvs=["45233223"],
        tender_nuts="DE21",
        tender_budget_eur=100_000,
        tender_country="DEU",
        capabilities=caps,
    )
    scorer = LogisticRegressionScorer.from_json(DEFAULT_PARAMS_PATH)
    assert scorer is not None
    assert set(computed) == set(scorer.feature_names)


def test_computed_features_round_trip_through_the_real_scorer() -> None:
    """End-to-end: a real feature dict scores against the committed model with no
    KeyError and yields a probability in [0, 1]."""
    caps = {
        "cpv_codes": ["45233000"],
        "nuts_codes": ["DE21"],
        "deal_size_eur": {"min": 30_000, "max": 500_000, "median": 100_000},
        "regions": ["DEU"],
        "award_count": 12,
    }
    computed = features.compute_features(
        semantic_score=0.82,
        tender_cpvs=["45233223"],
        tender_nuts="DE21",
        tender_budget_eur=100_000,
        tender_country="DEU",
        capabilities=caps,
    )
    scorer = LogisticRegressionScorer.from_json(DEFAULT_PARAMS_PATH)
    assert scorer is not None
    p = scorer.score(computed)
    assert 0.0 <= p <= 1.0
    # contributions must cover every feature (used in the match explanation).
    assert set(scorer.contributions(computed)) == set(features.FEATURE_NAMES)


def test_feedback_model_if_present_also_matches_feature_names() -> None:
    """A retrained feedback model must obey the same feature contract — otherwise
    load_active() would serve a model whose names the pipeline can't fill."""
    if not FEEDBACK_PARAMS_PATH.exists():
        pytest.skip("no feedback-tuned model on disk")
    params = _load(FEEDBACK_PARAMS_PATH)
    assert params["feature_names"] == features.FEATURE_NAMES
