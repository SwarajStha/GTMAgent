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
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# exports/ sits at the repo root: backend/app/matching/lr_weights.py → parents[3].
DEFAULT_PARAMS_PATH = Path(__file__).resolve().parents[3] / "exports" / "model_params.json"
# Feedback-tuned params (Step 5). When present, served in preference to the v5
# base — delete this file to revert to the v5 model.
FEEDBACK_PARAMS_PATH = DEFAULT_PARAMS_PATH.parent / "model_params_feedback.json"
# Below this many feedback rows (or with a single class) retraining refuses and
# the base model keeps serving. Tunable per call / via the retrain endpoint.
MIN_FEEDBACK_SAMPLES = 10


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

    @classmethod
    def load_active(cls) -> LogisticRegressionScorer | None:
        """Load the active scorer: feedback-tuned model if present, else v5 base.

        Returns None if neither params file exists (the pipeline then falls back
        to its legacy fixed-weight combine).
        """
        for path in (FEEDBACK_PARAMS_PATH, DEFAULT_PARAMS_PATH):
            scorer = cls.from_json(path)
            if scorer is not None:
                return scorer
        return None

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


class FeedbackRetrainer:
    """Retrain the matcher's LR weights from human thumbs-up/down feedback (G8).

    Reads the `feedback.features` snapshots + ratings (Step 5), fits a fresh
    StandardScaler + LogisticRegression, and writes `model_params_feedback.json`
    in the same shape the serving scorer loads — so `load_active()` then prefers
    it over the v5 base. Guarded: needs at least `min_samples` rows AND both
    classes present, otherwise it refuses and leaves the base model in place.

    sklearn/numpy are imported lazily inside `retrain()` so importing this module
    (and the matching pipeline) stays sklearn-free.
    """

    def __init__(
        self,
        min_samples: int = MIN_FEEDBACK_SAMPLES,
        out_path: Path | str = FEEDBACK_PARAMS_PATH,
    ) -> None:
        self.min_samples = max(2, int(min_samples))
        self.out_path = Path(out_path)

    def collect(self, session: Session) -> tuple[list[list[float]], list[int]]:
        """Build (X feature vectors, y labels) from feedback with snapshots."""
        import sqlalchemy as sa

        from app.db.models import Feedback
        from app.matching.features import FEATURE_NAMES

        rows = session.execute(
            sa.select(Feedback.features, Feedback.rating).where(Feedback.features.is_not(None))
        ).all()
        X: list[list[float]] = []
        y: list[int] = []
        for feats, rating in rows:
            if not feats:
                continue
            try:
                vec = [float(feats[name]) for name in FEATURE_NAMES]
            except (KeyError, TypeError, ValueError):
                continue  # malformed snapshot — skip
            X.append(vec)
            y.append(1 if rating > 0 else 0)
        return X, y

    def retrain(self, session: Session) -> dict[str, Any]:
        """Fit on feedback and write the feedback params; or report 'insufficient'."""
        from app.matching.features import FEATURE_NAMES

        X, y = self.collect(session)
        n = len(y)
        n_pos = sum(y)
        n_neg = n - n_pos
        if n < self.min_samples or n_pos == 0 or n_neg == 0:
            return {
                "status": "insufficient",
                "n_samples": n,
                "n_pos": n_pos,
                "n_neg": n_neg,
                "min_required": self.min_samples,
            }

        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        Xa = np.asarray(X, dtype=float)
        ya = np.asarray(y, dtype=int)
        scaler = StandardScaler().fit(Xa)
        model = LogisticRegression(
            C=1.0, max_iter=1000, class_weight="balanced", random_state=42
        )
        model.fit(scaler.transform(Xa), ya)

        params = {
            "feature_names": FEATURE_NAMES,
            "coefficients": model.coef_[0].tolist(),
            "intercept": float(model.intercept_[0]),
            "scaler_mean": scaler.mean_.tolist(),
            "scaler_scale": scaler.scale_.tolist(),
            "source": "feedback",
            "n_samples": n,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "trained_at": datetime.utcnow().isoformat() + "Z",
        }
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.out_path.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "retrained",
            "n_samples": n,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "out_path": str(self.out_path),
            "coefficients": dict(zip(FEATURE_NAMES, params["coefficients"])),
        }


# Backwards-compatible alias for the old stub name, in case anything imported it.
LogisticRegressionWeightLearner = LogisticRegressionScorer
