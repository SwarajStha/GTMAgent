"""
diagnostics.py – Feature diagnostics, data quality, and class weight comparison.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats as scipy_stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

BASE_DIR = Path(__file__).parent
MODEL_DIR = BASE_DIR / "models"

RANDOM_STATE = 42


def feature_diagnostics(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    lr_pipeline: Pipeline,
) -> dict[str, Any]:
    """
    Per-feature diagnostics: coefficients, odds ratios, class separation, QA flags.
    Saves results to models/feature_diagnostics.json.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)

    scaler: StandardScaler = lr_pipeline.named_steps["scaler"]
    clf_name = list(lr_pipeline.named_steps.keys())[-1]
    clf = lr_pipeline.named_steps[clf_name]
    if not hasattr(clf, "coef_"):
        print(f"[Diagnostics] Classifier {clf_name} has no coef_, skipping coefficient analysis.")
        coefs = np.zeros(len(feature_names))
    else:
        coefs = clf.coef_[0]

    pos_mask = y == 1
    neg_mask = y == 0

    features_info: list[dict[str, Any]] = []
    for i, name in enumerate(feature_names):
        col = X[:, i]
        col_valid = col[~np.isnan(col)]
        pos_vals = col[pos_mask & ~np.isnan(col)]
        neg_vals = col[neg_mask & ~np.isnan(col)]

        coef = float(coefs[i])
        odds_ratio = float(np.exp(coef))
        missing_rate = float(np.mean(np.isnan(col)))
        feat_mean = float(np.mean(col_valid)) if len(col_valid) else 0.0
        feat_std = float(np.std(col_valid)) if len(col_valid) else 0.0
        skewness = float(scipy_stats.skew(col_valid)) if len(col_valid) > 2 else 0.0
        pos_mean = float(np.mean(pos_vals)) if len(pos_vals) else 0.0
        neg_mean = float(np.mean(neg_vals)) if len(neg_vals) else 0.0

        entry: dict[str, Any] = {
            "feature": name,
            "raw_coefficient": round(coef, 6),
            "abs_coefficient": round(abs(coef), 6),
            "odds_ratio": round(odds_ratio, 6),
            "feature_mean": round(feat_mean, 6),
            "feature_std": round(feat_std, 6),
            "positive_class_mean": round(pos_mean, 6),
            "negative_class_mean": round(neg_mean, 6),
            "separation": round(pos_mean - neg_mean, 6),
            "skewness": round(skewness, 6),
            "missing_rate": round(missing_rate, 6),
            # QA flags
            "near_constant": bool(feat_std < 0.01),
            "high_skew": bool(abs(skewness) > 2),
            "high_missing": bool(missing_rate > 0.3),
        }
        features_info.append(entry)

    # Pearson correlation matrix
    corr_matrix = np.corrcoef(X.T).tolist() if X.shape[0] > 1 else []

    result: dict[str, Any] = {
        "features": features_info,
        "correlation_matrix": {
            "feature_names": feature_names,
            "values": corr_matrix,
        },
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MODEL_DIR / "feature_diagnostics.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[Diagnostics] Feature diagnostics saved to {out_path}")
    return result


def generate_data_quality_report(leads: list) -> dict[str, Any]:
    """
    Comprehensive data quality report for the lead list.
    Saves to models/data_quality_report.json.
    """
    total = len(leads)
    labeled = [l for l in leads if l.engagement is not None]
    positives = [l for l in labeled if l.engagement == 1]
    negatives = [l for l in labeled if l.engagement == 0]
    unlabeled = [l for l in leads if l.engagement is None]

    positive_rate = len(positives) / len(labeled) if labeled else 0.0

    # Date range
    dates = [l.published_at for l in leads if l.published_at]
    date_range = {"min": min(dates) if dates else None, "max": max(dates) if dates else None}

    # Duplicate tender IDs
    tid_counts = Counter(l.tender_id for l in leads)
    dup_count = sum(1 for c in tid_counts.values() if c > 1)

    # Missing rates per field
    def missing_rate(values):
        total_vals = len(values)
        if total_vals == 0:
            return 0.0
        missing = sum(1 for v in values if v is None or v == "" or
                      (isinstance(v, float) and np.isnan(v)))
        return round(missing / total_vals, 4)

    field_missing = {
        "tender_id": missing_rate([l.tender_id for l in leads]),
        "buyer": missing_rate([l.buyer for l in leads]),
        "region": missing_rate([l.region for l in leads]),
        "budget_eur": missing_rate([l.budget_eur for l in leads]),
        "deadline_days": missing_rate([l.deadline_days for l in leads]),
        "published_at": missing_rate([l.published_at for l in leads]),
    }

    feature_names = ["semantic_score", "budget_score", "region_score", "urgency_score", "competition_score"]
    feature_missing = {}
    for feat in feature_names:
        vals = [l.features.get(feat) for l in leads]
        feature_missing[feat] = missing_rate(vals)

    # Buyer stats
    buyer_counts = Counter(l.buyer for l in leads)
    unique_buyer_count = len(buyer_counts)
    buyer_freq_top20 = dict(buyer_counts.most_common(20))

    # Domain distribution
    domain_dist = dict(Counter(l.domain for l in leads))

    # Region distribution
    region_counts = Counter(l.region for l in leads)
    region_dist_top20 = dict(region_counts.most_common(20))

    # Label distribution by domain
    label_by_domain: dict[str, dict] = {}
    for l in labeled:
        d = l.domain
        if d not in label_by_domain:
            label_by_domain[d] = {"positive": 0, "negative": 0}
        if l.engagement == 1:
            label_by_domain[d]["positive"] += 1
        else:
            label_by_domain[d]["negative"] += 1

    # Label distribution by buyer (top 20)
    label_by_buyer: dict[str, dict] = {}
    for l in labeled:
        b = l.buyer
        if b not in label_by_buyer:
            label_by_buyer[b] = {"positive": 0, "negative": 0}
        if l.engagement == 1:
            label_by_buyer[b]["positive"] += 1
        else:
            label_by_buyer[b]["negative"] += 1
    top20_buyers = [b for b, _ in buyer_counts.most_common(20)]
    label_by_buyer_top20 = {b: label_by_buyer.get(b, {}) for b in top20_buyers}

    report: dict[str, Any] = {
        "total_samples": total,
        "labeled_samples": len(labeled),
        "unlabeled_samples": len(unlabeled),
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "positive_rate": round(positive_rate, 4),
        "date_range": date_range,
        "duplicate_tender_id_count": dup_count,
        "missing_rate_per_field": field_missing,
        "missing_rate_per_feature": feature_missing,
        "unique_buyer_count": unique_buyer_count,
        "buyer_frequency_distribution_top20": buyer_freq_top20,
        "domain_distribution": domain_dist,
        "region_distribution_top20": region_dist_top20,
        "label_distribution_by_domain": label_by_domain,
        "label_distribution_by_buyer_top20": label_by_buyer_top20,
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MODEL_DIR / "data_quality_report.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[Diagnostics] Data quality report saved to {out_path}")
    return report


def compare_class_weights(
    X_dev: np.ndarray,
    y_dev: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
) -> dict[str, Any]:
    """
    Compare different class_weight settings using internal dev-set split.
    Selection is based ONLY on dev set – test set is never used for selection.

    Returns
    -------
    dict with per-weight metrics and "best_class_weight" key.
    """
    class_weight_options = [
        None,
        "balanced",
        {0: 1, 1: 1},
        {0: 1, 1: 2},
        {0: 1, 1: 3},
        {0: 1, 1: 5},
    ]

    # Internal dev split for selection (no test data)
    if len(y_dev) < 10:
        X_sel_tr, X_sel_va, y_sel_tr, y_sel_va = (
            X_dev, X_dev, y_dev, y_dev
        )
    else:
        X_sel_tr, X_sel_va, y_sel_tr, y_sel_va = train_test_split(
            X_dev, y_dev, test_size=0.3, random_state=RANDOM_STATE,
            stratify=y_dev if len(np.unique(y_dev)) > 1 else None,
        )

    results: dict[str, Any] = {}
    best_cw_key = "None"
    best_prauc = -1.0

    def _cw_key(cw) -> str:
        if cw is None:
            return "None"
        if isinstance(cw, str):
            return cw
        return str(cw)

    for cw in class_weight_options:
        key = _cw_key(cw)
        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(
                C=1.0, max_iter=2000,
                class_weight=cw,
                random_state=RANDOM_STATE,
            )),
        ])
        if len(np.unique(y_sel_tr)) < 2:
            results[key] = {"pr_auc_dev": None, "skipped": True}
            continue
        pipeline.fit(X_sel_tr, y_sel_tr)
        probs_va = pipeline.predict_proba(X_sel_va)[:, 1]

        if len(np.unique(y_sel_va)) < 2 or np.sum(y_sel_va) == 0:
            prauc_dev = None
        else:
            prauc_dev = round(float(average_precision_score(y_sel_va, probs_va)), 4)

        results[key] = {
            "class_weight": cw if not isinstance(cw, dict) else key,
            "pr_auc_dev": prauc_dev,
        }
        if prauc_dev is not None and prauc_dev > best_prauc:
            best_prauc = prauc_dev
            best_cw_key = key

    results["best_class_weight"] = best_cw_key
    print(f"[ClassWeight] Best class_weight by dev PR-AUC: {best_cw_key} ({best_prauc:.4f})")
    return results
