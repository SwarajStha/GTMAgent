"""
evaluation.py – Metrics and baseline comparison for lead scoring.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


# ─────────────────────────────────────────────────────────────
# Core ranking metrics
# ─────────────────────────────────────────────────────────────

def precision_at_k(y_true: np.ndarray, probs: np.ndarray, k: int) -> float:
    """Fraction of positives in the top-k ranked items."""
    y_true = np.asarray(y_true)
    probs = np.asarray(probs)
    if len(y_true) == 0 or k <= 0:
        return 0.0
    k = min(k, len(y_true))
    top_k_idx = np.argsort(probs)[::-1][:k]
    return float(np.mean(y_true[top_k_idx]))


def recall_at_k(y_true: np.ndarray, probs: np.ndarray, k: int) -> float:
    """Fraction of all positives captured in the top-k ranked items."""
    y_true = np.asarray(y_true)
    probs = np.asarray(probs)
    positives = int(np.sum(y_true))
    if positives == 0 or len(y_true) == 0 or k <= 0:
        return 0.0
    k = min(k, len(y_true))
    top_k_idx = np.argsort(probs)[::-1][:k]
    return float(np.sum(y_true[top_k_idx]) / positives)


def lift_at_k(y_true: np.ndarray, probs: np.ndarray, k: int) -> float:
    """Lift = Precision@K / positive_rate.  Returns 0 if positive_rate == 0."""
    y_true = np.asarray(y_true)
    positive_rate = float(np.mean(y_true))
    if positive_rate == 0.0:
        return 0.0
    return precision_at_k(y_true, probs, k) / positive_rate


# ─────────────────────────────────────────────────────────────
# Full metrics dict
# ─────────────────────────────────────────────────────────────

def compute_metrics(
    y_true: np.ndarray,
    probs: np.ndarray,
    threshold: float,
    label: str = "",
) -> dict[str, Any]:
    """
    Compute a comprehensive set of classification metrics.

    Returns a dict with keys:
      ROC-AUC, PR-AUC, Precision@5, Precision@10, Precision@20,
      Recall@10, Recall@20, Lift@10, Lift@20,
      accuracy, precision, recall, f1, confusion_matrix,
      brier_score, log_loss
    """
    y_true = np.asarray(y_true, dtype=int)
    probs = np.asarray(probs, dtype=float)

    n_classes = len(np.unique(y_true))
    preds = (probs >= threshold).astype(int)

    result: dict[str, Any] = {"label": label, "threshold": round(threshold, 4)}

    # AUC metrics – require both classes
    if n_classes >= 2:
        result["roc_auc"] = round(float(roc_auc_score(y_true, probs)), 4)
        result["pr_auc"] = round(float(average_precision_score(y_true, probs)), 4)
    else:
        result["roc_auc"] = None
        result["pr_auc"] = None

    # Ranking metrics
    result["precision_at_5"] = round(precision_at_k(y_true, probs, 5), 4)
    result["precision_at_10"] = round(precision_at_k(y_true, probs, 10), 4)
    result["precision_at_20"] = round(precision_at_k(y_true, probs, 20), 4)
    result["recall_at_10"] = round(recall_at_k(y_true, probs, 10), 4)
    result["recall_at_20"] = round(recall_at_k(y_true, probs, 20), 4)
    result["lift_at_10"] = round(lift_at_k(y_true, probs, 10), 4)
    result["lift_at_20"] = round(lift_at_k(y_true, probs, 20), 4)

    # Threshold-based classification metrics
    result["accuracy"] = round(float(accuracy_score(y_true, preds)), 4)
    result["precision"] = round(float(precision_score(y_true, preds, zero_division=0)), 4)
    result["recall"] = round(float(recall_score(y_true, preds, zero_division=0)), 4)
    result["f1"] = round(float(f1_score(y_true, preds, zero_division=0)), 4)
    result["confusion_matrix"] = confusion_matrix(y_true, preds, labels=[0, 1]).tolist()

    # Calibration metrics
    result["brier_score"] = round(float(brier_score_loss(y_true, probs)), 4)
    if n_classes >= 2 and len(y_true) > 0:
        result["log_loss"] = round(float(log_loss(y_true, probs)), 4)
    else:
        result["log_loss"] = None

    return result


# ─────────────────────────────────────────────────────────────
# Baseline comparison
# ─────────────────────────────────────────────────────────────

def compare_baselines(
    y_true: np.ndarray,
    probs_dict: dict[str, np.ndarray],
    positive_rate: float,
    threshold: float = 0.5,
) -> dict[str, dict[str, Any]]:
    """
    Compute metrics for each scoring method in probs_dict.

    Expected keys: "random", "positive_rate_baseline", "semantic_score",
    "business_rule_score", "model_probability", "final_priority_score"

    Prints which method is best by PR-AUC.
    """
    y_true = np.asarray(y_true, dtype=int)
    results: dict[str, dict[str, Any]] = {}

    for name, probs in probs_dict.items():
        probs = np.asarray(probs, dtype=float)
        results[name] = compute_metrics(y_true, probs, threshold=threshold, label=name)

    # Find best by PR-AUC
    best_name = None
    best_prauc = -1.0
    for name, m in results.items():
        prauc = m.get("pr_auc")
        if prauc is not None and prauc > best_prauc:
            best_prauc = prauc
            best_name = name

    if best_name:
        print(f"[Baseline Comparison] Best method by PR-AUC: {best_name} ({best_prauc:.4f})")

    return results
