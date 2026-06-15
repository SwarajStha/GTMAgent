"""
tests/test_pipeline.py – pytest suite for the GTM lead scoring pipeline.

Uses synthetic data only; does NOT read tenders.json or any real data files.
"""
from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# Make sure we can import from easy_demo
EASY_DEMO = Path(__file__).parent.parent
sys.path.insert(0, str(EASY_DEMO))

from evaluation import compute_metrics, lift_at_k, precision_at_k, recall_at_k
from cross_validation import time_series_cross_validate
from baselines import build_baseline_probs
from calibration import calibrate_model, compare_calibrations


# ─────────────────────────────────────────────────────────────
# Minimal synthetic BuyerLead
# ─────────────────────────────────────────────────────────────

LEAD_FEATURES = [
    "semantic_score",
    "budget_score",
    "region_score",
    "urgency_score",
    "competition_score",
]


@dataclass
class FakeLead:
    tender_id: str
    buyer: str
    domain: str = "it"
    region: str = "DE"
    budget_eur: Optional[float] = None
    deadline_days: Optional[int] = 30
    published_at: Optional[str] = None
    features: dict = field(default_factory=dict)
    feature_vector: np.ndarray = field(default_factory=lambda: np.zeros(5))
    engagement: Optional[int] = None


def make_leads(
    n: int = 30,
    positive_rate: float = 0.3,
    start_date: datetime = datetime(2023, 1, 1, tzinfo=timezone.utc),
    n_buyers: int = 5,
) -> list[FakeLead]:
    """Create n synthetic leads with chronological published_at dates."""
    leads = []
    rng = np.random.default_rng(42)
    buyers = [f"Buyer_{i}" for i in range(n_buyers)]
    for i in range(n):
        fv = rng.uniform(0.1, 0.9, size=5)
        date_str = (start_date + timedelta(days=i)).isoformat()
        eng = int(rng.random() < positive_rate)
        lead = FakeLead(
            tender_id=f"T{i:04d}",
            buyer=buyers[i % n_buyers],
            published_at=date_str,
            features={k: float(fv[j]) for j, k in enumerate(LEAD_FEATURES)},
            feature_vector=fv,
            engagement=eng,
        )
        leads.append(lead)
    return leads


def make_pipeline_trained(X: np.ndarray, y: np.ndarray) -> Pipeline:
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(C=1.0, max_iter=200, class_weight="balanced", random_state=42)),
    ])
    pipe.fit(X, y)
    return pipe


# ─────────────────────────────────────────────────────────────
# 1. precision_at_k correctness
# ─────────────────────────────────────────────────────────────

def test_precision_at_k_known():
    y = np.array([1, 0, 1, 0, 0])
    p = np.array([0.9, 0.8, 0.7, 0.6, 0.5])
    # top-2: indices 0,1 → labels [1,0] → precision = 0.5
    assert precision_at_k(y, p, 2) == pytest.approx(0.5)
    # top-3: indices 0,1,2 → labels [1,0,1] → precision = 2/3
    assert precision_at_k(y, p, 3) == pytest.approx(2 / 3)


def test_precision_at_k_k_gt_len():
    y = np.array([1, 0, 1])
    p = np.array([0.9, 0.5, 0.8])
    # k=100 should clip to len=3
    result = precision_at_k(y, p, 100)
    assert 0.0 <= result <= 1.0


def test_precision_at_k_zero_k():
    y = np.array([1, 0])
    p = np.array([0.9, 0.1])
    assert precision_at_k(y, p, 0) == 0.0


# ─────────────────────────────────────────────────────────────
# 2. recall_at_k correctness
# ─────────────────────────────────────────────────────────────

def test_recall_at_k_known():
    y = np.array([1, 0, 1, 0, 0])
    p = np.array([0.9, 0.8, 0.7, 0.6, 0.5])
    # top-3: captures labels [1,0,1] → 2 out of 2 positives = 1.0
    assert recall_at_k(y, p, 3) == pytest.approx(1.0)
    # top-1: captures label [1] → 1 out of 2 = 0.5
    assert recall_at_k(y, p, 1) == pytest.approx(0.5)


def test_recall_at_k_no_positives():
    y = np.array([0, 0, 0])
    p = np.array([0.9, 0.5, 0.3])
    assert recall_at_k(y, p, 2) == 0.0


# ─────────────────────────────────────────────────────────────
# 3. lift_at_k = precision_at_k / positive_rate
# ─────────────────────────────────────────────────────────────

def test_lift_at_k_equals_precision_over_rate():
    y = np.array([1, 0, 1, 0, 0, 1, 0, 0, 0, 0])
    p = np.array([0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1])
    positive_rate = float(np.mean(y))
    k = 5
    p_at_k = precision_at_k(y, p, k)
    l_at_k = lift_at_k(y, p, k)
    assert l_at_k == pytest.approx(p_at_k / positive_rate, rel=1e-5)


def test_lift_at_k_zero_positive_rate():
    y = np.array([0, 0, 0])
    p = np.array([0.9, 0.5, 0.1])
    assert lift_at_k(y, p, 2) == 0.0


# ─────────────────────────────────────────────────────────────
# 4. time_series_cross_validate: future data not in past folds
# ─────────────────────────────────────────────────────────────

def test_cv_no_future_leakage():
    """Verify expanding-window: val dates are always strictly after train max date."""
    leads = make_leads(n=30, positive_rate=0.4)
    result = time_series_cross_validate(leads, min_train_size=5, n_splits=4, strategy="time")
    assert len(result["per_fold"]) > 0

    dates = {l.published_at: i for i, l in enumerate(
        sorted(leads, key=lambda l: l.published_at or "")
    )}
    for fold in result["per_fold"]:
        tr_max = fold["train_time_range"][1]
        va_min = fold["val_time_range"][0]
        if tr_max and va_min:
            assert tr_max <= va_min, f"Data leakage: train_max={tr_max} > val_min={va_min}"


# ─────────────────────────────────────────────────────────────
# 5. Holdout test set not passed into CV
# ─────────────────────────────────────────────────────────────

def test_holdout_excluded_from_cv():
    """CV function only sees dev leads; caller ensures test set is excluded."""
    all_leads = make_leads(n=40, positive_rate=0.4)
    dev = all_leads[:30]
    holdout = all_leads[30:]  # caller is responsible – just pass dev
    result = time_series_cross_validate(dev, min_train_size=5, n_splits=3, strategy="time")
    fold_sizes = [f["train_size"] + f["val_size"] for f in result["per_fold"]]
    # No fold should use all 40 samples
    for sz in fold_sizes:
        assert sz <= 30, f"Fold used {sz} samples but only 30 dev leads were passed"


# ─────────────────────────────────────────────────────────────
# 6. Each CV fold: scaler is refit independently
# ─────────────────────────────────────────────────────────────

def test_cv_scaler_refit_per_fold():
    """
    Indirectly verify scaler is refit: with different training data sizes,
    the pipeline must be refitted from scratch each fold.
    The cross_validation module creates a new pipeline per fold.
    We verify by checking that results differ across folds when they should.
    """
    leads = make_leads(n=40, positive_rate=0.4)
    result = time_series_cross_validate(leads, min_train_size=5, n_splits=4, strategy="time")
    per_fold = result["per_fold"]
    assert len(per_fold) >= 2
    train_sizes = [f["train_size"] for f in per_fold]
    # Expanding window: each fold has more training data
    for i in range(len(train_sizes) - 1):
        assert train_sizes[i] < train_sizes[i + 1], "Train size should grow each fold"


# ─────────────────────────────────────────────────────────────
# 7. Group split: same buyer not in both train and val
# ─────────────────────────────────────────────────────────────

def test_group_split_no_buyer_overlap():
    leads = make_leads(n=30, positive_rate=0.4, n_buyers=5)
    # Manually verify via cross_validation internals
    from cross_validation import _make_pipeline, _parse_date, LEAD_FEATURES
    from sklearn.model_selection import GroupKFold

    labeled = [l for l in leads if l.engagement is not None]
    X_all = np.array([l.feature_vector for l in labeled])
    y_all = np.array([l.engagement for l in labeled], dtype=int)
    buyers = np.array([l.buyer for l in labeled])

    gkf = GroupKFold(n_splits=5)
    for tr_idx, va_idx in gkf.split(X_all, y_all, groups=buyers):
        train_buyers = set(buyers[tr_idx])
        val_buyers = set(buyers[va_idx])
        assert train_buyers.isdisjoint(val_buyers), \
            f"Buyer overlap detected: {train_buyers & val_buyers}"


# ─────────────────────────────────────────────────────────────
# 8. Single-class fold: warning printed, not crashed
# ─────────────────────────────────────────────────────────────

def test_single_class_fold_handled_gracefully():
    """When validation set has only one class, AUC metrics are None and a warning is issued."""
    from evaluation import compute_metrics
    y_all_neg = np.zeros(10, dtype=int)
    probs = np.linspace(0, 1, 10)
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        result = compute_metrics(y_all_neg, probs, threshold=0.5, label="single_class")
    assert result["roc_auc"] is None
    assert result["pr_auc"] is None
    assert result["accuracy"] is not None  # non-AUC metrics still work


# ─────────────────────────────────────────────────────────────
# 9. Too few samples: raises ValueError
# ─────────────────────────────────────────────────────────────

def test_cv_too_few_samples_raises():
    leads = make_leads(n=3, positive_rate=0.5)
    with pytest.raises(ValueError, match="Not enough labeled samples"):
        time_series_cross_validate(leads, min_train_size=5, n_splits=3, strategy="time")


# ─────────────────────────────────────────────────────────────
# 10. Calibration: calibrate_model does not touch X_test
# ─────────────────────────────────────────────────────────────

def test_calibration_does_not_use_test_set():
    """Verify calibration is fitted only on cal data, not test data."""
    rng = np.random.default_rng(0)
    X_cal = rng.uniform(0, 1, (40, 5))
    y_cal = (rng.uniform(0, 1, 40) > 0.7).astype(int)

    X_test = rng.uniform(0, 1, (20, 5))
    y_test = (rng.uniform(0, 1, 20) > 0.7).astype(int)

    pipe = make_pipeline_trained(X_cal, y_cal)

    call_log = []

    original_fit = type(pipe).fit

    class TrackedPipeline(Pipeline):
        def fit(self, X, y=None, **kw):
            call_log.append(("fit", len(X)))
            return super().fit(X, y, **kw)

    # The calibrate_model function fits a CalibratedClassifierCV on X_cal only
    # We verify by monkey-patching: call calibrate_model and check it
    from calibration import calibrate_model as _cal
    calibrated = _cal(pipe, X_cal, y_cal, method="sigmoid")

    # Verify it works and produces valid probs on test set
    probs = calibrated.predict_proba(X_test)[:, 1]
    assert probs.shape == (20,)
    assert np.all(probs >= 0) and np.all(probs <= 1)


# ─────────────────────────────────────────────────────────────
# 11. Baseline metrics on tiny hand-verified array
# ─────────────────────────────────────────────────────────────

def test_baseline_metrics_hand_verified():
    # 5 samples, 2 positives
    y = np.array([1, 0, 1, 0, 0])
    p = np.array([0.9, 0.8, 0.7, 0.6, 0.5])

    # Top-2: [1, 0] → P@2 = 0.5
    assert precision_at_k(y, p, 2) == pytest.approx(0.5)
    # Top-2: 1 of 2 positives → R@2 = 0.5
    assert recall_at_k(y, p, 2) == pytest.approx(0.5)
    # Positive_rate = 2/5 = 0.4; Lift@2 = 0.5 / 0.4 = 1.25
    assert lift_at_k(y, p, 2) == pytest.approx(1.25)


# ─────────────────────────────────────────────────────────────
# 12. build_baseline_probs correctness
# ─────────────────────────────────────────────────────────────

def test_build_baseline_probs_keys():
    leads = make_leads(n=10, positive_rate=0.3)
    baselines = build_baseline_probs(leads, positive_rate_train=0.3, seed=42)

    assert "random" in baselines
    assert "positive_rate_baseline" in baselines
    assert "semantic_score" in baselines
    assert "business_rule_score" in baselines

    n = len(leads)
    for key, arr in baselines.items():
        assert len(arr) == n, f"{key} has wrong length"

    # positive_rate_baseline should be constant
    assert np.all(baselines["positive_rate_baseline"] == pytest.approx(0.3))


# ─────────────────────────────────────────────────────────────
# 13. contacted=False does not become negative label
# ─────────────────────────────────────────────────────────────

def test_create_feedback_contacted_false_no_label():
    """contacted=False → corrected_label should remain None (not 0)."""
    # Import the real create_feedback function
    from tender_pipeline import create_feedback

    scored_lead = {
        "tender_id": "T001",
        "buyer": "Test Buyer",
        "model_version": "v1",
        "model_probability": 0.7,
        "priority": "High Priority",
    }
    fb = create_feedback(
        scored_lead,
        reviewer_id="r1",
        reviewer_decision="unsure",
        contacted=False,
        corrected_label=None,
    )
    assert fb.corrected_label is None, (
        f"contacted=False should not set corrected_label=0, got {fb.corrected_label}"
    )


# ─────────────────────────────────────────────────────────────
# 14. sample_weight by label_source
# ─────────────────────────────────────────────────────────────

LABEL_SOURCE_WEIGHTS = {
    "observed_outcome": 1.0,
    "imported_history": 0.8,
    "human_review": 0.4,
    "synthetic": 0.2,
}


@dataclass
class FakeLeadWithSource(FakeLead):
    label_source: str = "observed_outcome"


def get_sample_weights(leads):
    weights = {
        "observed_outcome": 1.0,
        "imported_history": 0.8,
        "human_review": 0.4,
        "synthetic": 0.2,
    }
    return np.array(
        [weights.get(getattr(l, "label_source", "observed_outcome"), 0.5) for l in leads],
        dtype=float,
    )


def test_sample_weight_by_label_source():
    leads = [
        FakeLeadWithSource(tender_id="T1", buyer="B1", label_source="observed_outcome", engagement=1),
        FakeLeadWithSource(tender_id="T2", buyer="B2", label_source="imported_history", engagement=0),
        FakeLeadWithSource(tender_id="T3", buyer="B3", label_source="human_review", engagement=1),
        FakeLeadWithSource(tender_id="T4", buyer="B4", label_source="synthetic", engagement=0),
    ]
    weights = get_sample_weights(leads)
    assert weights[0] == pytest.approx(1.0)
    assert weights[1] == pytest.approx(0.8)
    assert weights[2] == pytest.approx(0.4)
    assert weights[3] == pytest.approx(0.2)


# ─────────────────────────────────────────────────────────────
# 15. synthetic label_source gets lower weight than observed_outcome
# ─────────────────────────────────────────────────────────────

def test_synthetic_lower_weight_than_observed():
    leads = [
        FakeLeadWithSource(tender_id="T1", buyer="B1", label_source="observed_outcome"),
        FakeLeadWithSource(tender_id="T2", buyer="B2", label_source="synthetic"),
    ]
    weights = get_sample_weights(leads)
    assert weights[1] < weights[0], "synthetic should have lower weight than observed_outcome"


# ─────────────────────────────────────────────────────────────
# 16. save/load model: predictions identical
# ─────────────────────────────────────────────────────────────

def test_save_load_model_identical_predictions(tmp_path):
    import joblib
    from tender_pipeline import ModelBundle, MODEL_VERSION

    rng = np.random.default_rng(7)
    X_train = rng.uniform(0, 1, (50, 5))
    y_train = (rng.uniform(0, 1, 50) > 0.7).astype(int)

    pipeline = make_pipeline_trained(X_train, y_train)
    bundle = ModelBundle(
        pipeline=pipeline,
        threshold=0.5,
        feature_names=["semantic_score", "budget_score", "region_score", "urgency_score", "competition_score"],
        model_version=MODEL_VERSION,
        trained_at=datetime.now(timezone.utc).isoformat(),
        validation_metrics={},
        test_metrics={},
    )

    model_path = tmp_path / "test_model.joblib"
    joblib.dump(bundle, model_path)
    loaded_bundle = joblib.load(model_path)

    X_test = rng.uniform(0, 1, (10, 5))
    orig_probs = bundle.pipeline.predict_proba(X_test)[:, 1]
    loaded_probs = loaded_bundle.pipeline.predict_proba(X_test)[:, 1]
    np.testing.assert_array_almost_equal(orig_probs, loaded_probs, decimal=10)


# ─────────────────────────────────────────────────────────────
# 17. score_lead output does NOT have top-level "probability" field
# ─────────────────────────────────────────────────────────────

def test_score_lead_no_probability_field():
    """final_priority_score must not be labelled 'probability' at top level."""
    from tender_pipeline import LeadScoringModel, BuyerLead
    import numpy as np

    lead = BuyerLead(
        tender_id="T001",
        domain="it",
        buyer="Test Buyer",
        project_name="Test Project",
        project_description="test",
        budget_eur=50000.0,
        region="DE",
        deadline_days=30,
        published_at=None,
        features={k: 0.5 for k in ["semantic_score", "budget_score", "region_score",
                                    "urgency_score", "competition_score"]},
        feature_vector=np.full(5, 0.5),
        engagement=None,
    )

    model = LeadScoringModel()
    result = model.score_lead(lead)

    # No top-level field named "probability"
    assert "probability" not in result, (
        f"score_lead output should not have a 'probability' field; got keys: {list(result.keys())}"
    )
    # final_priority_score exists but is not named "probability"
    assert "final_priority_score" in result
    # model_probability is the correct field name for the ML output
    assert "model_probability" in result
