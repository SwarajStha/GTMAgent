"""
cross_validation.py – Time-series and group cross-validation for lead scoring.
"""
from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from evaluation import precision_at_k, recall_at_k
from sklearn.metrics import roc_auc_score, average_precision_score

RANDOM_STATE = 42
LEAD_FEATURES = [
    "semantic_score",
    "budget_score",
    "region_score",
    "urgency_score",
    "competition_score",
]


def _make_pipeline() -> Pipeline:
    return Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(
            C=1.0, max_iter=2000,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        )),
    ])


def _parse_date(lead) -> datetime:
    pub = getattr(lead, "published_at", None) or ""
    try:
        return datetime.fromisoformat(pub.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min


def _fold_metrics(y_true: np.ndarray, probs: np.ndarray) -> dict[str, Any]:
    n_classes = len(np.unique(y_true))
    result: dict[str, Any] = {}
    if n_classes < 2:
        warnings.warn(
            f"[CV WARNING] Validation fold has only one class ({y_true[0]}). "
            "AUC metrics skipped for this fold.",
            UserWarning,
            stacklevel=3,
        )
        result["roc_auc"] = None
        result["pr_auc"] = None
    else:
        result["roc_auc"] = round(float(roc_auc_score(y_true, probs)), 4)
        result["pr_auc"] = round(float(average_precision_score(y_true, probs)), 4)

    result["precision_at_10"] = round(precision_at_k(y_true, probs, 10), 4)
    result["precision_at_20"] = round(precision_at_k(y_true, probs, 20), 4)
    result["recall_at_20"] = round(recall_at_k(y_true, probs, 20), 4)
    return result


def time_series_cross_validate(
    leads: list,
    min_train_size: int = 5,
    n_splits: int = 5,
    strategy: str = "time",  # "time" | "group" | "group_time"
) -> dict[str, Any]:
    """
    Cross-validate using expanding-window (time) or GroupKFold splits.

    Parameters
    ----------
    leads        : list of BuyerLead with engagement label (must NOT include holdout set)
    min_train_size : minimum samples required in first training fold
    n_splits     : number of CV folds
    strategy     : "time" | "group" | "group_time"

    Returns
    -------
    dict with "per_fold" (list of fold dicts) and "summary" (mean/std/min/max)
    """
    labeled = [l for l in leads if l.engagement is not None]
    if len(labeled) < min_train_size + 1:
        raise ValueError(
            f"Not enough labeled samples for cross-validation. "
            f"Need ≥ {min_train_size + 1}, got {len(labeled)}."
        )

    # Sort chronologically for time-based strategies
    if strategy in ("time", "group_time"):
        labeled = sorted(labeled, key=_parse_date)

    X_all = np.array([l.feature_vector for l in labeled])
    y_all = np.array([l.engagement for l in labeled], dtype=int)
    buyers = np.array([l.buyer for l in labeled])
    dates = [_parse_date(l) for l in labeled]

    per_fold: list[dict[str, Any]] = []

    if strategy == "time":
        n = len(labeled)
        step = max(1, (n - min_train_size) // n_splits)
        folds = []
        for i in range(n_splits):
            train_end = min_train_size + i * step
            val_start = train_end
            val_end = min(val_start + step, n)
            if val_start >= n or val_end > n:
                break
            folds.append((list(range(0, train_end)), list(range(val_start, val_end))))

    elif strategy == "group":
        gkf = GroupKFold(n_splits=n_splits)
        folds = list(gkf.split(X_all, y_all, groups=buyers))

    elif strategy == "group_time":
        # Sort groups by first appearance time, then apply GroupKFold
        gkf = GroupKFold(n_splits=n_splits)
        folds = list(gkf.split(X_all, y_all, groups=buyers))
        # Keep chronological order within folds
        folds = [(sorted(tr), sorted(va)) for tr, va in folds]

    else:
        raise ValueError(f"Unknown strategy: {strategy!r}. Choose 'time', 'group', or 'group_time'.")

    for fold_i, (train_idx, val_idx) in enumerate(folds):
        train_idx = list(train_idx)
        val_idx = list(val_idx)

        if len(train_idx) < min_train_size:
            print(f"[CV] Fold {fold_i}: too few train samples ({len(train_idx)}), skipping.")
            continue
        if len(val_idx) == 0:
            print(f"[CV] Fold {fold_i}: empty val set, skipping.")
            continue

        X_tr, y_tr = X_all[train_idx], y_all[train_idx]
        X_va, y_va = X_all[val_idx], y_all[val_idx]

        # Validate no future leakage for time strategy
        if strategy == "time":
            max_train_date = dates[max(train_idx)]
            min_val_date = dates[min(val_idx)]
            assert max_train_date <= min_val_date, \
                f"Data leakage: train max date {max_train_date} > val min date {min_val_date}"

        # Validate group separation
        if strategy in ("group", "group_time"):
            train_buyers = set(buyers[train_idx])
            val_buyers = set(buyers[val_idx])
            overlap = train_buyers & val_buyers
            if overlap:
                warnings.warn(
                    f"[CV] Fold {fold_i}: buyer overlap detected: {overlap}",
                    UserWarning,
                    stacklevel=2,
                )

        # Refit pipeline from scratch (no leakage)
        pipeline = _make_pipeline()
        if len(np.unique(y_tr)) < 2:
            print(f"[CV] Fold {fold_i}: training set has single class, skipping.")
            continue

        pipeline.fit(X_tr, y_tr)
        probs = pipeline.predict_proba(X_va)[:, 1]

        train_dates = [dates[i] for i in train_idx]
        val_dates = [dates[i] for i in val_idx]

        fold_result: dict[str, Any] = {
            "fold": fold_i,
            "train_size": len(train_idx),
            "val_size": len(val_idx),
            "positive_rate": round(float(np.mean(y_va)), 4),
            "train_time_range": (
                str(min(train_dates)) if train_dates else None,
                str(max(train_dates)) if train_dates else None,
            ),
            "val_time_range": (
                str(min(val_dates)) if val_dates else None,
                str(max(val_dates)) if val_dates else None,
            ),
        }
        fold_result.update(_fold_metrics(y_va, probs))
        per_fold.append(fold_result)

    if not per_fold:
        return {"per_fold": [], "summary": {}}

    # Summary statistics across folds
    metric_keys = ["roc_auc", "pr_auc", "precision_at_10", "precision_at_20", "recall_at_20"]
    summary: dict[str, Any] = {}
    for key in metric_keys:
        values = [f[key] for f in per_fold if f.get(key) is not None]
        if values:
            arr = np.array(values, dtype=float)
            summary[key] = {
                "mean": round(float(np.mean(arr)), 4),
                "std": round(float(np.std(arr)), 4),
                "min": round(float(np.min(arr)), 4),
                "max": round(float(np.max(arr)), 4),
            }
        else:
            summary[key] = {"mean": None, "std": None, "min": None, "max": None}

    print("\n[Cross-Validation Summary]")
    for key, stats in summary.items():
        if stats["mean"] is not None:
            print(f"  {key}: {stats['mean']:.4f} ± {stats['std']:.4f} "
                  f"(min={stats['min']:.4f}, max={stats['max']:.4f})")
        else:
            print(f"  {key}: N/A (single-class folds)")

    return {"per_fold": per_fold, "summary": summary}
