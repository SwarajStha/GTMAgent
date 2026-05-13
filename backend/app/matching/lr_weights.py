"""Logistic regression weight learner.

Trains a small LR model on the user-feedback table to learn per-feature
weights for the final score combiner. Designed for retraining as new
thumbs-up/down feedback rows accumulate.
"""
from __future__ import annotations


class LogisticRegressionWeightLearner:
    """Fits per-feature weights from match feedback."""

    # TODO: Phase 5 — load (features, label) rows from feedback table
    def load_training_data(self) -> tuple[list[list[float]], list[int]]:
        ...

    # TODO: Phase 5 — fit a logistic regression and return weight dict
    def fit(self) -> dict[str, float]:
        ...
