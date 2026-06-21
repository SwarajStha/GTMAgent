"""Unit tests for the LR scorer that loads v5's exported params (pure)."""
from __future__ import annotations

import json
import math

import pytest

from app.matching.features import FEATURE_NAMES
from app.matching.lr_weights import LogisticRegressionScorer


def _flat_features(value: float = 0.0) -> dict[str, float]:
    return {name: value for name in FEATURE_NAMES}


def test_all_zero_model_returns_half() -> None:
    scorer = LogisticRegressionScorer(
        feature_names=FEATURE_NAMES,
        coefficients=[0.0] * len(FEATURE_NAMES),
        intercept=0.0,
        scaler_mean=[0.0] * len(FEATURE_NAMES),
        scaler_scale=[1.0] * len(FEATURE_NAMES),
    )
    assert scorer.score(_flat_features(0.7)) == pytest.approx(0.5)


def test_score_matches_manual_sigmoid() -> None:
    # Single non-zero coefficient on semantic_score; identity scaler.
    coef = [0.0] * len(FEATURE_NAMES)
    coef[FEATURE_NAMES.index("semantic_score")] = 2.0
    scorer = LogisticRegressionScorer(
        feature_names=FEATURE_NAMES,
        coefficients=coef,
        intercept=-0.5,
        scaler_mean=[0.0] * len(FEATURE_NAMES),
        scaler_scale=[1.0] * len(FEATURE_NAMES),
    )
    feats = _flat_features(0.0)
    feats["semantic_score"] = 1.0
    expected = 1.0 / (1.0 + math.exp(-(-0.5 + 2.0 * 1.0)))
    assert scorer.score(feats) == pytest.approx(expected)


def test_contributions_sum_plus_intercept_recovers_logit() -> None:
    coef = [0.3] * len(FEATURE_NAMES)
    scorer = LogisticRegressionScorer(
        feature_names=FEATURE_NAMES,
        coefficients=coef,
        intercept=0.1,
        scaler_mean=[0.0] * len(FEATURE_NAMES),
        scaler_scale=[1.0] * len(FEATURE_NAMES),
    )
    feats = {name: 0.5 for name in FEATURE_NAMES}
    contrib = scorer.contributions(feats)
    logit = scorer.intercept + sum(contrib.values())
    assert scorer.score(feats) == pytest.approx(1.0 / (1.0 + math.exp(-logit)), abs=1e-6)


def test_zero_scale_is_guarded() -> None:
    scorer = LogisticRegressionScorer(
        feature_names=FEATURE_NAMES,
        coefficients=[1.0] * len(FEATURE_NAMES),
        intercept=0.0,
        scaler_mean=[0.0] * len(FEATURE_NAMES),
        scaler_scale=[0.0] * len(FEATURE_NAMES),  # would div-by-zero unguarded
    )
    # Should not raise; scale 0 is treated as 1.0.
    assert 0.0 <= scorer.score(_flat_features(0.5)) <= 1.0


def test_from_json_missing_file_returns_none(tmp_path) -> None:
    assert LogisticRegressionScorer.from_json(tmp_path / "nope.json") is None


def test_from_json_roundtrip(tmp_path) -> None:
    params = {
        "feature_names": FEATURE_NAMES,
        "coefficients": [0.1] * len(FEATURE_NAMES),
        "intercept": 0.2,
        "scaler_mean": [0.0] * len(FEATURE_NAMES),
        "scaler_scale": [1.0] * len(FEATURE_NAMES),
    }
    path = tmp_path / "model_params.json"
    path.write_text(json.dumps(params), encoding="utf-8")
    scorer = LogisticRegressionScorer.from_json(path)
    assert scorer is not None
    assert scorer.feature_names == FEATURE_NAMES
    assert 0.0 <= scorer.score(_flat_features(0.5)) <= 1.0
    assert set(scorer.contributions(_flat_features(0.5))) == set(FEATURE_NAMES)
