"""
baselines.py – Build and print baseline scoring distributions for comparison.
"""
from __future__ import annotations

from typing import Any

import numpy as np


MISSING_FILL = 0.5


def build_baseline_probs(
    leads_test: list,
    positive_rate_train: float,
    seed: int = 42,
) -> dict[str, np.ndarray]:
    """
    Build baseline probability arrays for the test leads.

    Returns a dict with keys:
      "random"                 – uniform random scores in [0, 1]
      "positive_rate_baseline" – constant = positive_rate_train
      "semantic_score"         – lead.features["semantic_score"]
      "business_rule_score"    – lead.features["business_rule_score"]

    Note: "model_probability" and "final_priority_score" are added by the caller.
    """
    rng = np.random.default_rng(seed)
    n = len(leads_test)

    random_scores = rng.uniform(0.0, 1.0, size=n)
    constant_scores = np.full(n, float(positive_rate_train))

    semantic_scores = np.array(
        [l.features.get("semantic_score", MISSING_FILL) for l in leads_test],
        dtype=float,
    )
    business_scores = np.array(
        [l.features.get("business_rule_score", MISSING_FILL) for l in leads_test],
        dtype=float,
    )

    return {
        "random": random_scores,
        "positive_rate_baseline": constant_scores,
        "semantic_score": semantic_scores,
        "business_rule_score": business_scores,
    }


def print_baseline_comparison(comparison_dict: dict[str, dict[str, Any]]) -> None:
    """
    Print a formatted table of baseline comparison metrics.
    Marks the best method per column with *.
    """
    columns = [
        ("ROC-AUC", "roc_auc"),
        ("PR-AUC", "pr_auc"),
        ("P@5", "precision_at_5"),
        ("P@10", "precision_at_10"),
        ("P@20", "precision_at_20"),
        ("R@10", "recall_at_10"),
        ("R@20", "recall_at_20"),
        ("Lift@10", "lift_at_10"),
        ("Lift@20", "lift_at_20"),
    ]

    methods = list(comparison_dict.keys())

    # Find best per column (higher is better for all metrics)
    best: dict[str, str] = {}
    for col_label, col_key in columns:
        best_method = None
        best_val = -1.0
        for m in methods:
            val = comparison_dict[m].get(col_key)
            if val is not None and float(val) > best_val:
                best_val = float(val)
                best_method = m
        if best_method is not None:
            best[col_key] = best_method

    # Header
    method_col_w = max(len(m) for m in methods) + 2
    col_w = 9
    header = f"{'Method':<{method_col_w}}" + "".join(f"{c[0]:>{col_w}}" for c in columns)
    print("\n" + "=" * len(header))
    print("[Baseline Comparison Table]")
    print(header)
    print("-" * len(header))

    for m in methods:
        row = f"{m:<{method_col_w}}"
        for col_label, col_key in columns:
            val = comparison_dict[m].get(col_key)
            if val is None:
                cell = "   N/A"
            else:
                marker = "*" if best.get(col_key) == m else " "
                cell = f"{marker}{float(val):7.4f}"
            row += f"{cell:>{col_w}}"
        print(row)

    print("=" * len(header))
    print("(* = best in column)\n")
