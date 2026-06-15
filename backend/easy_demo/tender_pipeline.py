"""
Tender GTM Pipeline / 投标 GTM 流水线
=====================================
目标：我方是卖方/供应商，通过EU招标公告找到潜在买家，评估其销售价值，
      为高质量线索生成个性化商务拓展邮件所需的上下文。

Process / 流程：
  1. Load tenders.json + company_profile.json
  2. Semantic match: do buyer's requirements align with what we sell?
  3. Rule-based lead scoring: budget tier / region / urgency / market competition
  4. Feature merging → LR (train/val/test split, threshold tuning, class balancing)
  5. Human-in-the-loop feedback storage and merge
  6. Output: ranked lead list + email context per buyer

Dependencies / 依赖：
  pip install numpy scikit-learn joblib
  pip install sentence-transformers   # only when USE_MINILM=True

Output files:
  data/scores_output.json
  data/human_feedback.jsonl
  models/lead_scoring_pipeline.joblib
  models/model_metadata.json
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# New modules
try:
    from evaluation import compute_metrics, compare_baselines
    from baselines import build_baseline_probs, print_baseline_comparison
    from cross_validation import time_series_cross_validate
    from calibration import calibrate_model, compare_calibrations, evaluate_calibration
    from diagnostics import feature_diagnostics, generate_data_quality_report, compare_class_weights
    _MODULES_AVAILABLE = True
except ImportError as _e:
    _MODULES_AVAILABLE = False
    print(f"[Warning] Could not import new modules: {_e}")


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

BASE_DIR      = Path(__file__).parent
DATA_DIR      = BASE_DIR / "data"
MODEL_DIR     = BASE_DIR / "models"

TENDERS_PATH  = DATA_DIR / "tenders.json"
VENDOR_PATH   = DATA_DIR / "company_profile.json"
FEEDBACK_PATH = DATA_DIR / "human_feedback.jsonl"
OUTPUT_PATH   = DATA_DIR / "scores_output.json"
MODEL_PATH    = MODEL_DIR / "lead_scoring_pipeline.joblib"
METADATA_PATH = MODEL_DIR / "model_metadata.json"

USE_MINILM    = True    # True = MiniLM (accurate, ~10s load); False = TF-IDF (fast, offline)
MINILM_MODEL  = "all-MiniLM-L6-v2"
RANDOM_STATE  = 42
MISSING_FILL  = 0.5
MODEL_VERSION = "lead_lr_v2"

LEAD_FEATURES = [
    "semantic_score",
    "budget_score",
    "region_score",
    "urgency_score",
    "competition_score",
]

DEFAULT_BUSINESS_WEIGHTS = {
    "semantic_score":    0.40,
    "budget_score":      0.20,
    "region_score":      0.15,
    "urgency_score":     0.15,
    "competition_score": 0.10,
}

# Final display score = alpha * model probability + beta * business score
MODEL_ALPHA   = 0.70
BUSINESS_BETA = 0.30


# ─────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────

@dataclass
class BuyerLead:
    tender_id: str
    domain: str
    buyer: str
    project_name: str
    project_description: str
    budget_eur: Optional[float]
    region: str
    deadline_days: Optional[int]
    published_at: Optional[str]
    features: dict[str, float] = field(default_factory=dict)
    feature_vector: np.ndarray = field(default_factory=lambda: np.array([]))
    engagement: Optional[int] = None  # 1=replied/meeting/deal, 0=ignored
    label_source: str = "observed_outcome"  # "observed_outcome"|"human_review"|"imported_history"|"synthetic"


@dataclass
class ModelBundle:
    pipeline: Pipeline
    threshold: float
    feature_names: list[str]
    model_version: str
    trained_at: str
    validation_metrics: dict[str, Any]
    test_metrics: dict[str, Any]


@dataclass
class HumanFeedback:
    feedback_id: str
    tender_id: str
    buyer: str
    model_version: str
    original_probability: float
    original_priority: str
    reviewer_id: str
    reviewer_decision: str
    reviewer_reason: str
    corrected_label: Optional[int]
    timestamp: str
    contacted: Optional[bool]
    replied: Optional[bool]
    meeting_booked: Optional[bool]
    converted_to_opportunity: Optional[bool]
    human_adjustment: float = 0.0
    # Extended fields for richer feedback tracking
    label_source: str = "human_review"          # "observed_outcome"|"human_review"|"imported_history"|"synthetic"
    feedback_confidence: float = 1.0            # reviewer's stated confidence 0-1
    outcome_observed_at: Optional[str] = None   # ISO timestamp when outcome was confirmed
    review_status: str = "submitted"            # "submitted"|"confirmed"|"disputed"
    previous_model_version: Optional[str] = None
    previous_prediction: Optional[float] = None


# ─────────────────────────────────────────────────────────────
# Step 0: Load and validate
# ─────────────────────────────────────────────────────────────

def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_data() -> tuple[list[dict], dict]:
    tenders = load_json(TENDERS_PATH)
    vendor  = load_json(VENDOR_PATH)
    if not isinstance(tenders, list):
        raise ValueError("tenders.json must contain a JSON list")
    if not isinstance(vendor, dict):
        raise ValueError("company_profile.json must contain a JSON object")
    print(f"[Load] {len(tenders)} tenders | Vendor: {vendor.get('company_name', 'Unknown')}")
    return tenders, vendor


def validate_binary_labels(leads: Iterable[BuyerLead]) -> None:
    invalid = [l.engagement for l in leads
               if l.engagement is not None and l.engagement not in (0, 1)]
    if invalid:
        raise ValueError(f"engagement labels must be 0 or 1, got: {invalid[:5]}")


_LABEL_SOURCE_WEIGHTS: dict[str, float] = {
    "observed_outcome": 1.0,
    "imported_history": 0.8,
    "human_review": 0.4,
    "synthetic": 0.2,
}


def get_sample_weights(leads: list[BuyerLead]) -> np.ndarray:
    """Return per-sample training weights based on label_source."""
    return np.array(
        [_LABEL_SOURCE_WEIGHTS.get(l.label_source, 0.5) for l in leads],
        dtype=float,
    )


# ─────────────────────────────────────────────────────────────
# Step 1: Semantic match — buyer's requirements vs our offerings
# ─────────────────────────────────────────────────────────────

class SemanticScorer:
    def __init__(self) -> None:
        self._vendor_texts: dict[str, str] = {}
        if USE_MINILM:
            from sentence_transformers import SentenceTransformer
            print(f"[MiniLM] Loading {MINILM_MODEL}")
            self._model = SentenceTransformer(MINILM_MODEL)
            self._vendor_embs: dict[str, np.ndarray] = {}
            self._tfidf = None
            self._vendor_vecs: dict[str, Any] = {}
        else:
            print("[Semantic] TF-IDF mode")
            self._model = None
            self._tfidf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
            self._vendor_vecs: dict[str, Any] = {}

    def build_vendor_embeddings(self, vendor: dict, tenders: list[dict]) -> None:
        profiles = vendor.get("capability_profiles", {})
        if not profiles:
            raise ValueError("vendor capability_profiles is missing or empty")
        self._vendor_texts = profiles

        if USE_MINILM:
            for domain, text in profiles.items():
                if text:
                    self._vendor_embs[domain] = self._model.encode(
                        text, convert_to_numpy=True,
                        normalize_embeddings=True, show_progress_bar=False,
                    )
        else:
            company_texts = [t for t in profiles.values() if t]
            tender_texts  = [t.get("project_description", "") for t in tenders]
            corpus = [t for t in company_texts + tender_texts if t]
            if not corpus:
                raise ValueError("No text available for TF-IDF")
            self._tfidf.fit(corpus)
            for domain, text in profiles.items():
                if text:
                    self._vendor_vecs[domain] = self._tfidf.transform([text])

        print(f"[Semantic] Vendor embedding built: {list(profiles.keys())}")

    def score(self, tender: dict) -> float:
        domain = tender.get("domain", "hybrid")
        if not self._vendor_texts.get(domain):
            domain = next((d for d, t in self._vendor_texts.items() if t), None)
        if domain is None:
            return MISSING_FILL

        buyer_text = tender.get("project_description", "")
        if not buyer_text:
            return MISSING_FILL

        if USE_MINILM:
            vendor_emb = self._vendor_embs.get(domain)
            if vendor_emb is None:
                return MISSING_FILL
            buyer_emb = self._model.encode(
                buyer_text, convert_to_numpy=True,
                normalize_embeddings=True, show_progress_bar=False,
            )
            cosine = float(np.dot(buyer_emb, vendor_emb))
        else:
            vendor_vec = self._vendor_vecs.get(domain)
            if vendor_vec is None:
                return MISSING_FILL
            buyer_vec = self._tfidf.transform([buyer_text])
            cosine = float(cosine_similarity(buyer_vec, vendor_vec)[0][0])

        return round(float(np.clip((cosine - 0.05) / 0.90, 0.0, 1.0)), 4)


# ─────────────────────────────────────────────────────────────
# Step 2: Rule-based lead scoring
# ─────────────────────────────────────────────────────────────

RATES_TO_EUR = {"EUR": 1.0, "DKK": 0.134, "GBP": 1.17, "USD": 0.92}


def convert_budget_to_eur(tender: dict) -> Optional[float]:
    budget   = tender.get("budget_original") or {}
    amount   = budget.get("amount")
    currency = budget.get("currency", "EUR")
    if amount is None:
        return None
    rate = RATES_TO_EUR.get(currency)
    return float(amount) * rate if rate else None


def score_budget(tender: dict, vendor: dict) -> float:
    amount_eur = convert_budget_to_eur(tender)
    if amount_eur is None:
        return MISSING_FILL
    target = vendor.get("target_deal_size_eur", {})
    lo = float(target.get("min", 0))
    hi = float(target.get("max", float("inf")))
    if lo <= amount_eur <= hi:
        return 1.0
    if amount_eur < lo:
        return round(float(amount_eur / lo), 4) if lo > 0 else MISSING_FILL
    return round(float(hi / amount_eur), 4) if np.isfinite(hi) else 1.0


def score_region(tender: dict, vendor: dict) -> float:
    region = str(tender.get("region", "")).strip().lower()
    if not region:
        return MISSING_FILL
    for target_region in vendor.get("target_regions", []):
        target = str(target_region).strip().lower()
        if target and (target in region or region in target):
            return 1.0
    return 0.2


def score_urgency(tender: dict) -> float:
    """Sweet-spot window scores highest; too-soon and too-far both score lower."""
    days = tender.get("deadline_days")
    if days is None:
        return MISSING_FILL
    if days <= 0:
        return 0.0
    if days <= 3:
        return 0.15   # too close to react
    if days <= 30:
        return 1.0
    if days <= 90:
        return round(float(1.0 - 0.3 * ((days - 30) / 60)), 4)
    if days <= 180:
        return round(float(0.7 - 0.5 * ((days - 90) / 90)), 4)
    return 0.1


def score_competition(tender: dict) -> float:
    received = tender.get("received_tenders")
    if received is None:
        return MISSING_FILL
    if received <= 0:
        return 0.9
    return round(float(np.clip(1.0 / float(received), 0.1, 1.0)), 4)


def build_vector(features: dict[str, float]) -> np.ndarray:
    return np.array([features.get(k, MISSING_FILL) for k in LEAD_FEATURES], dtype=float)


def process_tenders(tenders: list[dict], vendor: dict,
                    semantic_scorer: SemanticScorer) -> list[BuyerLead]:
    print("\n[Lead Scoring]")
    leads: list[BuyerLead] = []
    for t in tenders:
        features = {
            "semantic_score":    semantic_scorer.score(t),
            "budget_score":      score_budget(t, vendor),
            "region_score":      score_region(t, vendor),
            "urgency_score":     score_urgency(t),
            "competition_score": score_competition(t),
        }
        # prefer explicit engagement label, fall back to legacy result field
        engagement = t.get("engagement")
        if engagement is None:
            engagement = t.get("result")

        leads.append(BuyerLead(
            tender_id=t["tender_id"],
            domain=t.get("domain", "hybrid"),
            buyer=t.get("buyer", "Unknown Buyer"),
            project_name=t.get("project_name", ""),
            project_description=t.get("project_description", ""),
            budget_eur=convert_budget_to_eur(t),
            region=t.get("region", ""),
            deadline_days=t.get("deadline_days"),
            published_at=t.get("published_at") or t.get("publication_date"),
            features=features,
            feature_vector=build_vector(features),
            engagement=engagement,
        ))

    validate_binary_labels(leads)
    return leads


# ─────────────────────────────────────────────────────────────
# Step 3: Train / val / test split
# ─────────────────────────────────────────────────────────────

def split_labeled_leads(
    leads: list[BuyerLead],
    train_size: float = 0.70,
    val_size: float   = 0.15,
    test_size: float  = 0.15,
) -> tuple[list[BuyerLead], list[BuyerLead], list[BuyerLead]]:
    if not np.isclose(train_size + val_size + test_size, 1.0):
        raise ValueError("train_size + val_size + test_size must equal 1.0")

    labeled = [l for l in leads if l.engagement is not None]
    if len(labeled) < 8:
        raise ValueError(f"Need ≥8 labeled samples for a three-way split; got {len(labeled)}")
    if len({l.engagement for l in labeled}) < 2:
        raise ValueError("Labeled data must contain both positive and negative classes")

    # Chronological split when all rows have timestamps
    if all(l.published_at for l in labeled):
        try:
            ordered = sorted(labeled, key=lambda l: datetime.fromisoformat(
                l.published_at.replace("Z", "+00:00")))
            n = len(ordered)
            train_end = max(1, int(n * train_size))
            val_end   = max(train_end + 1, int(n * (train_size + val_size)))
            train, val, test = ordered[:train_end], ordered[train_end:val_end], ordered[val_end:]
            if test and len({l.engagement for l in train}) >= 2:
                print("[Split] chronological train/val/test")
                return train, val, test
        except (TypeError, ValueError):
            pass

    # Stratified fallback
    train, temp = train_test_split(
        labeled, test_size=val_size + test_size,
        stratify=[l.engagement for l in labeled], random_state=RANDOM_STATE,
    )
    val, test = train_test_split(
        temp, test_size=test_size / (val_size + test_size),
        stratify=[l.engagement for l in temp], random_state=RANDOM_STATE,
    )
    print("[Split] stratified train/val/test")
    return train, val, test


# ─────────────────────────────────────────────────────────────
# Step 4: Metrics and threshold selection
# ─────────────────────────────────────────────────────────────

def precision_at_k(y_true: np.ndarray, probs: np.ndarray, k: int) -> float:
    k = min(k, len(y_true))
    return float(np.mean(y_true[np.argsort(probs)[::-1][:k]])) if k else 0.0


def recall_at_k(y_true: np.ndarray, probs: np.ndarray, k: int) -> float:
    positives = int(np.sum(y_true))
    if not positives:
        return 0.0
    k = min(k, len(y_true))
    return float(np.sum(y_true[np.argsort(probs)[::-1][:k]]) / positives)


def evaluate_predictions(y_true: np.ndarray, probs: np.ndarray,
                         threshold: float) -> dict[str, Any]:
    preds = (probs >= threshold).astype(int)
    metrics: dict[str, Any] = {
        "threshold":      round(float(threshold), 4),
        "sample_count":   int(len(y_true)),
        "positive_rate":  round(float(np.mean(y_true)), 4),
        "accuracy":       round(float(accuracy_score(y_true, preds)), 4),
        "precision":      round(float(precision_score(y_true, preds, zero_division=0)), 4),
        "recall":         round(float(recall_score(y_true, preds, zero_division=0)), 4),
        "f1":             round(float(f1_score(y_true, preds, zero_division=0)), 4),
        "confusion_matrix": confusion_matrix(y_true, preds, labels=[0, 1]).tolist(),
        "precision_at_10":  round(precision_at_k(y_true, probs, 10), 4),
        "precision_at_20":  round(precision_at_k(y_true, probs, 20), 4),
        "recall_at_20":     round(recall_at_k(y_true, probs, 20), 4),
    }
    metrics["roc_auc"] = (
        round(float(roc_auc_score(y_true, probs)), 4)
        if len(np.unique(y_true)) == 2 else None
    )
    metrics["pr_auc"] = (
        round(float(average_precision_score(y_true, probs)), 4)
        if np.sum(y_true) > 0 else None
    )
    return metrics


def select_threshold(y_true: np.ndarray, probs: np.ndarray) -> float:
    best_threshold, best_f1 = 0.5, -1.0
    for threshold in np.linspace(0.05, 0.95, 91):
        current_f1 = f1_score(y_true, (probs >= threshold).astype(int), zero_division=0)
        if current_f1 > best_f1:
            best_f1, best_threshold = current_f1, float(threshold)
    return best_threshold


# ─────────────────────────────────────────────────────────────
# Step 5: Lead scoring model
# ─────────────────────────────────────────────────────────────

class LeadScoringModel:
    def __init__(self, bundle: Optional[ModelBundle] = None) -> None:
        if bundle is None:
            bundle = ModelBundle(
                pipeline=Pipeline([
                    ("scaler", StandardScaler()),
                    ("lr", LogisticRegression(
                        C=1.0, max_iter=2000,
                        class_weight="balanced", random_state=RANDOM_STATE,
                    )),
                ]),
                threshold=0.5,
                feature_names=list(LEAD_FEATURES),
                model_version=MODEL_VERSION,
                trained_at="",
                validation_metrics={},
                test_metrics={},
            )
        self.bundle  = bundle
        self.trained = bool(bundle.trained_at)

    def train(self, leads: list[BuyerLead]) -> ModelBundle:
        train, val, test = split_labeled_leads(leads)

        X_train = np.array([l.feature_vector for l in train])
        y_train = np.array([l.engagement for l in train], dtype=int)
        if len(np.unique(y_train)) < 2:
            raise ValueError("Training split must contain both classes")

        sample_weights = get_sample_weights(train)
        # Fit scaler and classifier separately to pass sample_weight (sklearn>=1.4 routing change)
        # Use dynamic last-step lookup so any classifier (LR, RF, HGB) works.
        scaler = self.bundle.pipeline.named_steps["scaler"]
        clf_name = list(self.bundle.pipeline.named_steps.keys())[-1]
        clf_step = self.bundle.pipeline.named_steps[clf_name]
        X_train_scaled = scaler.fit_transform(X_train)
        try:
            clf_step.fit(X_train_scaled, y_train, sample_weight=sample_weights)
        except TypeError:
            # Classifier doesn't support sample_weight (rare), fall back
            clf_step.fit(X_train_scaled, y_train)

        X_val = np.array([l.feature_vector for l in val])
        y_val = np.array([l.engagement for l in val], dtype=int)
        val_probs = self.bundle.pipeline.predict_proba(X_val)[:, 1]
        threshold = select_threshold(y_val, val_probs)

        X_test = np.array([l.feature_vector for l in test])
        y_test = np.array([l.engagement for l in test], dtype=int)
        test_probs = self.bundle.pipeline.predict_proba(X_test)[:, 1]

        self.bundle.threshold         = threshold
        self.bundle.trained_at        = datetime.now(timezone.utc).isoformat()
        self.bundle.validation_metrics = evaluate_predictions(y_val, val_probs, threshold)
        self.bundle.test_metrics       = evaluate_predictions(y_test, test_probs, threshold)
        self.trained = True
        return self.bundle

    def predict_probability(self, vector: np.ndarray) -> float:
        if not self.trained:
            raise RuntimeError("Model is not trained")
        return float(self.bundle.pipeline.predict_proba(vector.reshape(1, -1))[0][1])

    def explain(self, vector: np.ndarray, top_n: int = 3) -> list[dict[str, Any]]:
        if not self.trained:
            return []
        scaled = self.bundle.pipeline.named_steps["scaler"].transform(vector.reshape(1, -1))[0]
        clf_name = list(self.bundle.pipeline.named_steps.keys())[-1]
        clf = self.bundle.pipeline.named_steps[clf_name]
        # Only LR exposes coef_; tree-based models use feature_importances_
        if hasattr(clf, "coef_"):
            weights_arr = clf.coef_[0]
            contribs = scaled * weights_arr
            direction_fn = lambda c: "positive" if c >= 0 else "negative"
            items = [
                {"feature": f, "value": round(float(v), 4),
                 "contribution": round(float(c), 4),
                 "direction": direction_fn(c)}
                for f, v, c in zip(LEAD_FEATURES, vector, contribs)
            ]
        elif hasattr(clf, "feature_importances_"):
            importances = clf.feature_importances_
            items = [
                {"feature": f, "value": round(float(v), 4),
                 "contribution": round(float(imp), 4),
                 "direction": "positive"}
                for f, v, imp in zip(LEAD_FEATURES, vector, importances)
            ]
        else:
            return []
        return sorted(items, key=lambda x: abs(x["contribution"]), reverse=True)[:top_n]

    def business_rule_score(self, lead: BuyerLead,
                             weights: Optional[dict[str, float]] = None) -> float:
        weights = weights or DEFAULT_BUSINESS_WEIGHTS
        w = {k: max(0.0, float(weights.get(k, 0.0))) for k in LEAD_FEATURES}
        total = sum(w.values())
        if total == 0:
            raise ValueError("At least one business weight must be positive")
        return float(sum(w[k] * lead.features.get(k, MISSING_FILL) for k in LEAD_FEATURES) / total)

    def score_lead(
        self,
        lead: BuyerLead,
        human_adjustment: float = 0.0,
        business_weights: Optional[dict[str, float]] = None,
        mode: str = "hybrid",                    # "model_only" | "business_only" | "hybrid"
        calibrated_pipeline: Any = None,         # optional calibrated classifier
    ) -> dict[str, Any]:
        """
        Score a lead.

        Modes:
          "model_only"     – final_priority_score = raw_model_probability + adjustment
          "business_only"  – final_priority_score = business_rule_score + adjustment
          "hybrid"         – final_priority_score = 0.7 * model + 0.3 * business + adjustment
        """
        business_score = self.business_rule_score(lead, business_weights)

        if self.trained:
            raw_model_probability = self.predict_probability(lead.feature_vector)
            # Calibrated probability (if a calibrated pipeline is available)
            if calibrated_pipeline is not None:
                try:
                    calibrated_probability = float(
                        calibrated_pipeline.predict_proba(
                            lead.feature_vector.reshape(1, -1)
                        )[0][1]
                    )
                except Exception:
                    calibrated_probability = raw_model_probability
            else:
                calibrated_probability = raw_model_probability
            top_factors = self.explain(lead.feature_vector)
            threshold   = self.bundle.threshold
        else:
            raw_model_probability  = business_score
            calibrated_probability = business_score
            top_factors = []
            threshold   = 0.5

        human_adjustment = float(np.clip(human_adjustment, -0.30, 0.30))

        if mode == "model_only":
            base_score = raw_model_probability
        elif mode == "business_only":
            base_score = business_score
        else:  # hybrid (default)
            base_score = MODEL_ALPHA * raw_model_probability + BUSINESS_BETA * business_score

        final_score = float(np.clip(base_score + human_adjustment, 0.0, 1.0))

        # ── Hard-rule post-processing ─────────────────────────
        # Penalise leads that are structurally incompatible with our vendor profile.
        filter_reason: Optional[str] = None
        semantic = lead.features.get("semantic_score", MISSING_FILL)
        region_s = lead.features.get("region_score", MISSING_FILL)

        if lead.domain == "it" and semantic < 0.20:
            # Pure IT tender with no semantic overlap → force Skip
            final_score = min(final_score, 0.20)
            filter_reason = "IT domain with very low semantic match"
        elif region_s <= 0.2 and semantic < 0.15:
            # Wrong region AND wrong content → strong penalisation
            final_score = min(final_score, 0.25)
            filter_reason = "Out-of-region and low semantic match"

        # Geographic tier bonus: reward tenders in our primary German markets
        PRIMARY_REGIONS = {"germany", "deutschland", "bayern", "hessen",
                           "badenwürttemberg", "nordrhein-westfalen"}
        region_lower = lead.region.lower()
        if any(r in region_lower for r in PRIMARY_REGIONS):
            final_score = float(np.clip(final_score + 0.04, 0.0, 1.0))

        return {
            "tender_id":               lead.tender_id,
            "buyer":                   lead.buyer,
            "domain":                  lead.domain,
            "region":                  lead.region,
            "budget_eur":              lead.budget_eur,
            "model_version":           self.bundle.model_version,
            "raw_model_probability":   round(raw_model_probability, 4),
            "model_probability":       round(raw_model_probability, 4),   # alias for backward compat
            "calibrated_probability":  round(calibrated_probability, 4),
            "business_rule_score":     round(business_score, 4),
            "human_adjustment":        round(human_adjustment, 4),
            "scoring_mode":            mode,
            "final_priority_score":    round(final_score, 4),
            "final_priority_score_100": round(final_score * 100, 1),
            "prediction":              int(raw_model_probability >= threshold),
            "threshold":               round(threshold, 4),
            "priority":                priority_label(final_score),
            "filter_reason":           filter_reason,
            "top_factors":             top_factors,
            "email_context": {
                "buyer_name":          lead.buyer,
                "project_name":        lead.project_name,
                "project_description": lead.project_description,
                "region":              lead.region,
                "budget_eur":          lead.budget_eur,
                "deadline_days":       lead.deadline_days,
            },
        }


def priority_label(score: float) -> str:
    if score >= 0.70: return "High Priority"
    if score >= 0.50: return "Medium Priority"
    if score >= 0.35: return "Low Priority"
    return "Skip"


# ─────────────────────────────────────────────────────────────
# Model persistence
# ─────────────────────────────────────────────────────────────

def save_model(bundle: ModelBundle) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODEL_PATH)
    with METADATA_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "model_version":      bundle.model_version,
            "trained_at":         bundle.trained_at,
            "feature_names":      bundle.feature_names,
            "threshold":          bundle.threshold,
            "validation_metrics": bundle.validation_metrics,
            "test_metrics":       bundle.test_metrics,
        }, f, ensure_ascii=False, indent=2)
    print(f"[Model] Saved to {MODEL_PATH}")


def load_model() -> LeadScoringModel:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Saved model not found: {MODEL_PATH}")
    bundle = joblib.load(MODEL_PATH)
    if not isinstance(bundle, ModelBundle):
        raise TypeError("Saved object is not a ModelBundle")
    return LeadScoringModel(bundle)


# ─────────────────────────────────────────────────────────────
# Step 6: Human-in-the-loop feedback
# ─────────────────────────────────────────────────────────────

VALID_REVIEW_DECISIONS = {"approve", "reject", "increase_priority", "decrease_priority", "unsure"}


def create_feedback(
    scored_lead: dict[str, Any],
    reviewer_id: str,
    reviewer_decision: str,
    reviewer_reason: str = "",
    corrected_label: Optional[int] = None,
    contacted: Optional[bool] = None,
    replied: Optional[bool] = None,
    meeting_booked: Optional[bool] = None,
    converted_to_opportunity: Optional[bool] = None,
    human_adjustment: float = 0.0,
) -> HumanFeedback:
    if reviewer_decision not in VALID_REVIEW_DECISIONS:
        raise ValueError(f"Invalid reviewer_decision: {reviewer_decision!r}")
    if corrected_label not in (None, 0, 1):
        raise ValueError("corrected_label must be None, 0, or 1")

    if contacted is False:
        corrected_label = None
    if any(v is True for v in (replied, meeting_booked, converted_to_opportunity)):
        corrected_label = 1
    elif contacted is True and replied is False and meeting_booked is False \
            and converted_to_opportunity is False:
        corrected_label = 0

    return HumanFeedback(
        feedback_id=str(uuid.uuid4()),
        tender_id=scored_lead["tender_id"],
        buyer=scored_lead["buyer"],
        model_version=scored_lead["model_version"],
        original_probability=float(scored_lead["model_probability"]),
        original_priority=scored_lead["priority"],
        reviewer_id=reviewer_id,
        reviewer_decision=reviewer_decision,
        reviewer_reason=reviewer_reason,
        corrected_label=corrected_label,
        timestamp=datetime.now(timezone.utc).isoformat(),
        contacted=contacted,
        replied=replied,
        meeting_booked=meeting_booked,
        converted_to_opportunity=converted_to_opportunity,
        human_adjustment=float(np.clip(human_adjustment, -0.30, 0.30)),
    )


def append_feedback(feedback: HumanFeedback, path: Path = FEEDBACK_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids: set[str] = set()
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    existing_ids.add(json.loads(line)["feedback_id"])
    if feedback.feedback_id in existing_ids:
        raise ValueError(f"Duplicate feedback_id: {feedback.feedback_id}")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(feedback), ensure_ascii=False) + "\n")


def load_confirmed_feedback(path: Path = FEEDBACK_PATH) -> dict[str, int]:
    """Return latest confirmed outcome label per tender for retraining."""
    if not path.exists():
        return {}
    latest: dict[str, tuple[str, int]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row   = json.loads(line)
            label = row.get("corrected_label")
            if label not in (0, 1):
                continue
            tid   = row["tender_id"]
            ts    = row.get("timestamp", "")
            if tid not in latest or ts > latest[tid][0]:
                latest[tid] = (ts, int(label))
    return {tid: label for tid, (_, label) in latest.items()}


def merge_confirmed_feedback(leads: list[BuyerLead]) -> None:
    confirmed = load_confirmed_feedback()
    for lead in leads:
        if lead.tender_id in confirmed:
            lead.engagement = confirmed[lead.tender_id]


# ─────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────

def _compare_classifiers(
    X_dev: np.ndarray,
    y_dev: np.ndarray,
) -> tuple[str, Pipeline]:
    """
    Minimal comparison: LR vs RandomForest vs HistGradientBoosting.
    Selection by PR-AUC on internal dev split. No GridSearch.
    Returns (best_name, fitted_pipeline_on_full_dev).
    """
    from sklearn.model_selection import train_test_split as _tts
    try:
        X_tr, X_va, y_tr, y_va = _tts(
            X_dev, y_dev, test_size=0.3, random_state=RANDOM_STATE,
            stratify=y_dev if len(np.unique(y_dev)) > 1 else None,
        )
    except ValueError:
        X_tr, X_va, y_tr, y_va = X_dev, X_dev, y_dev, y_dev

    classifiers = {
        "LogisticRegression": Pipeline([
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(C=1.0, max_iter=2000,
                                      class_weight="balanced",
                                      random_state=RANDOM_STATE)),
        ]),
        "RandomForest": Pipeline([
            ("scaler", StandardScaler()),
            ("rf", RandomForestClassifier(n_estimators=100, class_weight="balanced",
                                          random_state=RANDOM_STATE, n_jobs=-1)),
        ]),
        "HistGradientBoosting": Pipeline([
            ("scaler", StandardScaler()),
            ("hgb", HistGradientBoostingClassifier(max_iter=100, random_state=RANDOM_STATE)),
        ]),
    }

    best_name = "LogisticRegression"
    best_prauc = -1.0
    print("\n[Classifier Comparison]")
    for name, pipe in classifiers.items():
        if len(np.unique(y_tr)) < 2:
            print(f"  {name}: skipped (single class in train)")
            continue
        pipe.fit(X_tr, y_tr)
        probs = pipe.predict_proba(X_va)[:, 1]
        if len(np.unique(y_va)) >= 2 and np.sum(y_va) > 0:
            prauc = float(average_precision_score(y_va, probs))
        else:
            prauc = 0.0
        print(f"  {name}: PR-AUC={prauc:.4f}")
        if prauc > best_prauc:
            best_prauc = prauc
            best_name = name

    print(f"  → Best classifier: {best_name}")
    # Refit best on full dev
    best_pipe = classifiers[best_name]
    if len(np.unique(y_dev)) >= 2:
        best_pipe.fit(X_dev, y_dev)
    return best_name, best_pipe


def main() -> None:
    tenders, vendor = load_data()

    semantic_scorer = SemanticScorer()
    semantic_scorer.build_vendor_embeddings(vendor, tenders)
    leads = process_tenders(tenders, vendor, semantic_scorer)
    merge_confirmed_feedback(leads)

    # Compute business_rule_score as a feature for each lead
    _tmp_model = LeadScoringModel()
    for lead in leads:
        lead.features["business_rule_score"] = _tmp_model.business_rule_score(lead)

    model = LeadScoringModel()
    labeled_count  = sum(l.engagement is not None for l in leads)
    unique_labels  = {l.engagement for l in leads if l.engagement is not None}

    # ── Data quality report ──────────────────────────────────
    if _MODULES_AVAILABLE:
        generate_data_quality_report(leads)

    model_report: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    cv_results: dict = {}
    calibration_results: dict = {}
    best_scoring_mode = "hybrid"
    calibrated_pipeline = None
    best_prauc_test: Optional[float] = None
    best_brier: Optional[float] = None

    if labeled_count >= 8 and len(unique_labels) == 2:
        train, val, test = split_labeled_leads(leads)
        dev = train + val  # everything except holdout test

        X_dev  = np.array([l.feature_vector for l in dev])
        y_dev  = np.array([l.engagement for l in dev], dtype=int)
        X_test = np.array([l.feature_vector for l in test])
        y_test = np.array([l.engagement for l in test], dtype=int)

        # ── Class weight comparison on dev ───────────────────
        if _MODULES_AVAILABLE:
            cw_results = compare_class_weights(X_dev, y_dev, X_test, y_test)
            model_report["class_weight_comparison"] = cw_results

        # ── Classifier comparison on dev ─────────────────────
        best_clf_name, best_clf_pipeline = _compare_classifiers(X_dev, y_dev)
        model_report["best_classifier"] = best_clf_name

        # Update model's pipeline to best classifier
        model.bundle.pipeline = best_clf_pipeline

        # ── Cross-validation on dev ──────────────────────────
        if _MODULES_AVAILABLE:
            try:
                cv_results = time_series_cross_validate(dev, min_train_size=5, n_splits=5)
                model_report["cv_results"] = cv_results
            except ValueError as exc:
                print(f"[CV] Skipped: {exc}")

        # ── Full train on labeled data ────────────────────────
        bundle = model.train(leads)
        save_model(bundle)
        print("\n[Validation metrics]")
        print(json.dumps(bundle.validation_metrics, indent=2))
        print("[Test metrics]")
        print(json.dumps(bundle.test_metrics, indent=2))

        # ── Feature diagnostics ──────────────────────────────
        if _MODULES_AVAILABLE:
            X_all_labeled = np.array([l.feature_vector for l in leads if l.engagement is not None])
            y_all_labeled = np.array([l.engagement for l in leads if l.engagement is not None], dtype=int)
            try:
                feature_diagnostics(X_all_labeled, y_all_labeled, LEAD_FEATURES, model.bundle.pipeline)
            except Exception as exc:
                print(f"[Diagnostics] Feature diagnostics skipped: {exc}")

        # ── Calibration ──────────────────────────────────────
        if _MODULES_AVAILABLE:
            try:
                calibration_results = compare_calibrations(
                    model.bundle.pipeline, X_dev, y_dev, X_test, y_test
                )
                best_cal_method = calibration_results.get("best_method", "none")
                calibrated_pipeline = calibrate_model(
                    model.bundle.pipeline, X_dev, y_dev, method=best_cal_method
                )
                best_brier = calibration_results.get(best_cal_method, {}).get("brier_score_calibrated")
                model_report["calibration"] = calibration_results
            except Exception as exc:
                print(f"[Calibration] Skipped: {exc}")

        # ── Baseline comparison on test ──────────────────────
        if _MODULES_AVAILABLE:
            try:
                positive_rate_train = float(np.mean(y_dev))
                baselines = build_baseline_probs(test, positive_rate_train)

                test_model_probs = model.bundle.pipeline.predict_proba(X_test)[:, 1]
                baselines["model_probability"] = test_model_probs

                # Build final scores for test leads
                test_results_raw = [model.score_lead(l, calibrated_pipeline=calibrated_pipeline)
                                    for l in test]
                baselines["final_priority_score"] = np.array(
                    [r["final_priority_score"] for r in test_results_raw]
                )

                comparison = compare_baselines(y_test, baselines, positive_rate=positive_rate_train)
                print_baseline_comparison(comparison)
                model_report["baseline_comparison"] = comparison

                # Select best scoring mode by PR-AUC on dev
                mode_paucs: dict[str, float] = {}
                dev_model_probs = model.bundle.pipeline.predict_proba(X_dev)[:, 1]
                for mode_name in ("model_only", "business_only", "hybrid"):
                    dev_mode_results = [model.score_lead(l, mode=mode_name) for l in dev]
                    dev_mode_scores = np.array([r["final_priority_score"] for r in dev_mode_results])
                    if len(np.unique(y_dev)) >= 2 and np.sum(y_dev) > 0:
                        mode_paucs[mode_name] = float(average_precision_score(y_dev, dev_mode_scores))
                    else:
                        mode_paucs[mode_name] = 0.0

                best_scoring_mode = max(mode_paucs, key=mode_paucs.__getitem__)
                print(f"\n[Scoring Mode] Best by dev PR-AUC: {best_scoring_mode} "
                      f"({mode_paucs[best_scoring_mode]:.4f})")
                model_report["scoring_mode_comparison"] = mode_paucs
                model_report["best_scoring_mode"] = best_scoring_mode

                # Test set PR-AUC
                if "final_priority_score" in baselines and len(np.unique(y_test)) >= 2:
                    best_prauc_test = float(average_precision_score(
                        y_test, baselines["final_priority_score"]
                    ))
            except Exception as exc:
                print(f"[Baseline/Scoring] Skipped: {exc}")

    else:
        print(
            f"\n[Warning] Only {labeled_count} usable labeled rows or single class. "
            "Using business-rule score until enough historical outcomes exist."
        )

    # ── Score all leads ───────────────────────────────────────
    results = [
        model.score_lead(l, mode=best_scoring_mode, calibrated_pipeline=calibrated_pipeline)
        for l in leads
    ]
    results.sort(key=lambda r: r["final_priority_score"], reverse=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[Done] Results written to {OUTPUT_PATH}")

    print("\n[Top leads]")
    for r in results[:10]:
        budget_str = f"€{r['budget_eur']:,.0f}" if r['budget_eur'] else "N/A"
        print(
            f"  {r['tender_id']} | {r['buyer'][:35]:35s} | "
            f"model={r['raw_model_probability']:.3f} | "
            f"biz={r['business_rule_score']:.3f} | "
            f"final={r['final_priority_score_100']:5.1f} | "
            f"{r['priority']} | {budget_str}"
        )

    # ── Model report ──────────────────────────────────────────
    cv_summary = cv_results.get("summary", {})
    pr_auc_cv = cv_summary.get("pr_auc", {})

    model_report.update({
        "best_scoring_mode": best_scoring_mode,
        "holdout_pr_auc": best_prauc_test,
        "calibration_brier": best_brier,
        "limitations": [
            "Small labeled dataset may cause overfitting",
            "Chronological split may not reflect deployment distribution",
            "Semantic scores depend on quality of company_profile.json",
        ],
    })

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    report_path = MODEL_DIR / "model_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(model_report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[Report] Model report saved to {report_path}")

    # ── Terminal summary ──────────────────────────────────────
    cv_mean = pr_auc_cv.get("mean")
    cv_std  = pr_auc_cv.get("std")
    cv_str  = f"{cv_mean:.4f} ± {cv_std:.4f}" if cv_mean is not None else "N/A"
    holdout_str = f"{best_prauc_test:.4f}" if best_prauc_test is not None else "N/A"
    brier_str = f"{best_brier:.6f}" if best_brier is not None else "N/A"
    best_ranking = model_report.get("best_classifier", "LogisticRegression")
    test_metrics = model.bundle.test_metrics if model.bundle.test_metrics else {}
    p10_str  = str(test_metrics.get("precision_at_10", "N/A"))
    p20_str  = str(test_metrics.get("precision_at_20", "N/A"))
    r20_str  = str(test_metrics.get("recall_at_20", "N/A"))

    print("""
=== MODEL REPORT SUMMARY ===
Best ranking method:          {best_ranking}
Best scoring mode:            {best_scoring_mode}
PR-AUC (test):                {holdout_str}
Precision@10:                 {p10_str}
Precision@20:                 {p20_str}
Recall@20:                    {r20_str}
Lift@10:                      N/A (see baseline table above)
CV mean ± std (PR-AUC):       {cv_str}
Holdout result (PR-AUC):      {holdout_str}
Calibration quality (Brier):  {brier_str}
Recommended production mode:  {best_scoring_mode}
Limitations:
  - Small labeled dataset may cause overfitting
  - Chronological split may not reflect deployment distribution
  - Semantic scores depend on quality of company_profile.json
""".format(
        best_ranking=best_ranking,
        best_scoring_mode=best_scoring_mode,
        holdout_str=holdout_str,
        p10_str=p10_str,
        p20_str=p20_str,
        r20_str=r20_str,
        cv_str=cv_str,
        brier_str=brier_str,
    ))


if __name__ == "__main__":
    main()
