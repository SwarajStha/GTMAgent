"""
calibration.py – Probability calibration utilities for lead scoring.
"""
from __future__ import annotations

from typing import Any, Union

import numpy as np
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
try:
    from sklearn.frozen import FrozenEstimator   # sklearn >= 1.6
    _HAS_FROZEN = True
except ImportError:
    _HAS_FROZEN = False
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline


def calibrate_model(
    base_pipeline: Pipeline,
    X_cal: np.ndarray,
    y_cal: np.ndarray,
    method: str = "sigmoid",
) -> Union[CalibratedClassifierCV, Pipeline]:
    """
    Fit calibration wrapper on calibration data only.

    Parameters
    ----------
    base_pipeline : already-fitted sklearn Pipeline (scaler + LR)
    X_cal         : calibration feature matrix (NOT test set)
    y_cal         : calibration labels
    method        : "sigmoid" | "isotonic" | "none"

    Returns
    -------
    Calibrated classifier (or original pipeline if method="none")
    """
    if method == "none":
        return base_pipeline

    if _HAS_FROZEN:
        estimator = FrozenEstimator(base_pipeline)
        calibrated = CalibratedClassifierCV(estimator, method=method)
    else:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            calibrated = CalibratedClassifierCV(base_pipeline, method=method, cv="prefit")
    calibrated.fit(X_cal, y_cal)
    return calibrated


def evaluate_calibration(
    y_true: np.ndarray,
    raw_probs: np.ndarray,
    calibrated_probs: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """
    Compare calibration quality of raw vs calibrated probabilities.

    Returns
    -------
    dict with:
      brier_score_raw, brier_score_calibrated,
      log_loss_raw, log_loss_calibrated,
      ece (Expected Calibration Error on calibrated probs),
      calibration_curve_data
    """
    y_true = np.asarray(y_true, dtype=int)
    raw_probs = np.asarray(raw_probs, dtype=float)
    calibrated_probs = np.asarray(calibrated_probs, dtype=float)

    n_classes = len(np.unique(y_true))

    brier_raw = float(brier_score_loss(y_true, raw_probs))
    brier_cal = float(brier_score_loss(y_true, calibrated_probs))

    if n_classes >= 2:
        ll_raw = float(log_loss(y_true, raw_probs))
        ll_cal = float(log_loss(y_true, calibrated_probs))
    else:
        ll_raw = None
        ll_cal = None

    # Expected Calibration Error (ECE) on calibrated probs
    # Use quantile strategy so every bin has samples → no shape mismatch
    fraction_of_positives, mean_predicted_value = calibration_curve(
        y_true, calibrated_probs, n_bins=min(n_bins, len(y_true) // 2 or 1),
        strategy="quantile",
    )
    n_bins_actual = len(fraction_of_positives)
    bin_edges = np.quantile(calibrated_probs, np.linspace(0, 1, n_bins_actual + 1))
    bin_counts = np.array([
        np.sum((calibrated_probs >= bin_edges[i]) & (calibrated_probs < bin_edges[i + 1]))
        for i in range(n_bins_actual)
    ], dtype=float)
    bin_counts[-1] += np.sum(calibrated_probs == bin_edges[-1])  # include right edge
    ece = float(np.sum(
        np.abs(fraction_of_positives - mean_predicted_value) * bin_counts
    ) / max(len(y_true), 1))

    return {
        "brier_score_raw": round(brier_raw, 6),
        "brier_score_calibrated": round(brier_cal, 6),
        "log_loss_raw": round(ll_raw, 6) if ll_raw is not None else None,
        "log_loss_calibrated": round(ll_cal, 6) if ll_cal is not None else None,
        "ece": round(ece, 6),
        "calibration_curve_data": {
            "fraction_of_positives": fraction_of_positives.tolist(),
            "mean_predicted_value": mean_predicted_value.tolist(),
        },
    }


def compare_calibrations(
    base_pipeline: Pipeline,
    X_cal: np.ndarray,
    y_cal: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
) -> dict[str, Any]:
    """
    Compare uncalibrated, sigmoid, and isotonic calibration.

    Calibration is fitted ONLY on (X_cal, y_cal).
    Selection is based on brier_score on X_test.

    Returns
    -------
    dict with per-method metrics and "best_method" key.
    """
    methods = ["none", "sigmoid", "isotonic"]
    results: dict[str, Any] = {}

    raw_probs_test = base_pipeline.predict_proba(X_test)[:, 1]

    best_method = "none"
    best_brier = float("inf")

    for method in methods:
        calibrated = calibrate_model(base_pipeline, X_cal, y_cal, method=method)

        if method == "none":
            cal_probs_test = raw_probs_test.copy()
        else:
            cal_probs_test = calibrated.predict_proba(X_test)[:, 1]

        eval_result = evaluate_calibration(
            y_test, raw_probs_test, cal_probs_test, n_bins=10
        )
        eval_result["method"] = method
        results[method] = eval_result

        if eval_result["brier_score_calibrated"] < best_brier:
            best_brier = eval_result["brier_score_calibrated"]
            best_method = method

    results["best_method"] = best_method
    print(f"[Calibration] Best method by Brier score on test: {best_method} "
          f"(Brier={best_brier:.6f})")
    return results
