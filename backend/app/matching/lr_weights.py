"""Logistic-regression scorer driven by the v5-exported model params.

The offline v5 pipeline (`exports_ml_pipeline.py`) trains the LR on the
backfilled awards and writes `exports/model_params.json`
(coefficients + intercept + StandardScaler mean/scale). This module loads those
and reproduces `predict_proba` in pure Python — no joblib, no sklearn at runtime,
so it stays torch/sklearn-free and version-independent.

`MatchingPipeline` uses this when the params file is present; if it is absent
(v5 not yet re-run) the pipeline falls back to the legacy fixed-weight combine,
so the app keeps working either way.

Phase-5 note: retraining from the `feedback` table (gap G8) will write a new
`model_params.json` (or a feedback-tuned sibling) in this same shape, so the
serving path here does not change.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

# exports/ sits at the repo root: backend/app/matching/lr_weights.py → parents[3].
DEFAULT_PARAMS_PATH = Path(__file__).resolve().parents[3] / "exports" / "model_params.json"


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


class LogisticRegressionScorer:
    """Applies v5's trained LR (scaled-feature space) to a feature dict."""

    def __init__(
        self,
        feature_names: list[str],
        coefficients: list[float],
        intercept: float,
        scaler_mean: list[float],
        scaler_scale: list[float],
    ) -> None:
        n = len(feature_names)
        if not (len(coefficients) == len(scaler_mean) == len(scaler_scale) == n):
            raise ValueError("model_params arrays must all match feature_names length")
        self.feature_names = list(feature_names)
        self.coefficients = [float(c) for c in coefficients]
        self.intercept = float(intercept)
        self.scaler_mean = [float(m) for m in scaler_mean]
        # Guard against a zero scale (constant feature) → avoid div-by-zero.
        self.scaler_scale = [float(s) if float(s) != 0.0 else 1.0 for s in scaler_scale]

    @classmethod
    def from_json(cls, path: Path | str | None = None) -> LogisticRegressionScorer | None:
        """Load the scorer, or return None if the params file does not exist."""
        p = Path(path) if path is not None else DEFAULT_PARAMS_PATH
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            feature_names=data["feature_names"],
            coefficients=data["coefficients"],
            intercept=data["intercept"],
            scaler_mean=data["scaler_mean"],
            scaler_scale=data["scaler_scale"],
        )

    def _logit_terms(self, features: dict[str, float]) -> list[float]:
        """Per-feature standardised contribution coef·(x-mean)/scale."""
        terms: list[float] = []
        for name, coef, mean, scale in zip(
            self.feature_names, self.coefficients, self.scaler_mean, self.scaler_scale
        ):
            z = (float(features[name]) - mean) / scale
            terms.append(coef * z)
        return terms

    def score(self, features: dict[str, float]) -> float:
        """P(win) in [0, 1] for one (tender, company) feature dict."""
        logit = self.intercept + sum(self._logit_terms(features))
        return _sigmoid(logit)

    def contributions(self, features: dict[str, float]) -> dict[str, float]:
        """Per-feature contribution to the logit, for the match explanation."""
        return {
            name: round(term, 4)
            for name, term in zip(self.feature_names, self._logit_terms(features))
        }

    def as_metadata(self) -> dict[str, Any]:
        """Snapshot of the model identity stored on each match's `weights` JSONB."""
        return {
            "model": "logistic_regression_v5",
            "intercept": round(self.intercept, 6),
            "coefficients": {
                n: round(c, 6) for n, c in zip(self.feature_names, self.coefficients)
            },
        }


# Backwards-compatible alias for the old stub name, in case anything imported it.
LogisticRegressionWeightLearner = LogisticRegressionScorer
