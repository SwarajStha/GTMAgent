# Tender GTM Lead Scoring Pipeline

A Go-To-Market pipeline that monitors EU public tender portals, identifies buyer organisations, scores them as sales leads, and produces ranked, email-ready output for business development teams.

The system adopts a **seller perspective**: given one vendor profile and a feed of public tenders, it answers "which buyers are worth reaching out to, and in what order?"

---

## Project Structure

```text
easy_demo/
├── tender_pipeline.py       # Main pipeline entry point
├── evaluation.py            # Metrics: PR-AUC, Precision@K, Recall@K, Lift@K
├── baselines.py             # Baseline rankers for comparison
├── cross_validation.py      # Expanding-window time-series CV
├── calibration.py           # Sigmoid / isotonic probability calibration
├── diagnostics.py           # Feature diagnostics and data quality report
├── requirements.txt
├── README.md
├── data/
│   ├── tenders.json             # Input: EU tender records
│   ├── company_profile.json     # Input: vendor (seller) profile
│   ├── human_feedback.jsonl     # Human-in-the-loop feedback log
│   └── scores_output.json       # Output: ranked lead list
├── models/
│   ├── lead_scoring_pipeline.joblib   # Saved model
│   ├── model_metadata.json
│   ├── model_report.json              # Full training report
│   ├── feature_diagnostics.json
│   └── data_quality_report.json
└── tests/
    └── test_pipeline.py         # pytest suite (21 tests)
```

---

## Architecture Overview

```text
EU Tender Feed (tenders.json)
        │
        ▼
 Feature Engineering
   ├── semantic_score      MiniLM cosine: buyer need vs vendor offering
   ├── budget_score        Buyer budget vs vendor target deal size
   ├── region_score        Buyer location vs vendor target markets
   ├── urgency_score       Deadline proximity (sweet-spot window)
   └── competition_score   Fewer competing bids = easier entry
        │
        ▼
 Lead Scoring Model
   ├── Class-weight comparison   (None / balanced / custom)
   ├── Classifier comparison     (LR / RandomForest / HistGradientBoosting)
   ├── Expanding-window time CV  (no future data leakage)
   └── Probability calibration   (sigmoid / isotonic)
        │
        ▼
 Final Priority Score
   = α × model_probability + β × business_rule_score + human_adjustment
   + geographic tier bonus (primary German markets)
   + hard-rule post-processing (IT domain filter, region penalty)
        │
        ▼
 Output: ranked leads + email_context per buyer → scores_output.json
```

---

## Input Files

### `data/company_profile.json`

Describes **your company as a seller** — what you offer, where you operate, and what deal sizes you target.

Key fields:

| Field | Description |
|---|---|
| `company_name` | Vendor name |
| `capability_profiles` | Rich text descriptions per domain (`construction`, `it`, `hybrid`). Quality here directly determines `semantic_score` accuracy. Expand these descriptions to cover all vocabulary your buyers might use. |
| `target_regions` | List of regions/countries you serve |
| `target_deal_size_eur` | `{ "min": 30000, "max": 500000 }` |

### `data/tenders.json`

A list of EU public tender records. Each tender represents a potential buyer lead.

Key fields:

| Field | Description |
|---|---|
| `tender_id` | Unique identifier |
| `domain` | `"construction"` / `"it"` / `"hybrid"` |
| `project_description` | Full text used for semantic scoring |
| `buyer` | Organisation that issued the tender (your sales target) |
| `budget_original` | `{ "amount": 101980.05, "currency": "EUR" }` |
| `region` | Buyer location |
| `deadline_days` | Days until submission deadline |
| `received_tenders` | Number of competing bids already received |
| `engagement` | Training label: `1` = buyer engaged after outreach, `0` = ignored. Leave `null` for unlabeled records. |
| `label_source` | `"observed_outcome"` / `"human_review"` / `"imported_history"` / `"synthetic"` |
| `published_at` | ISO date string — used for chronological train/val/test split |

---

## Scoring Logic

### Five features

| Feature | Meaning |
|---|---|
| `semantic_score` | MiniLM cosine similarity between buyer's project description and vendor's capability profile. High = buyer needs what you sell. |
| `budget_score` | How well buyer's budget matches your target deal size range. Scores 1.0 inside the range, decays outside. |
| `region_score` | 1.0 if buyer is in your target markets, 0.2 otherwise. |
| `urgency_score` | Peaks at 1–30 days remaining. Too close (≤3 days) or too far (>180 days) scores lower. |
| `competition_score` | Fewer competing bids = higher score. `null` received_tenders = 0.8 (open opportunity). |

### Final priority score

```
final_priority_score
  = α × model_probability          (default α = 0.70)
  + β × business_rule_score        (default β = 0.30)
  + human_adjustment               (range: –0.30 to +0.30)
  + geographic_bonus               (+0.04 for primary German markets)
```

Three scoring modes are supported: `model_only`, `business_only`, `hybrid`. The pipeline auto-selects the best mode by PR-AUC on the development set.

**Note:** `final_priority_score` is a ranking signal, not a calibrated probability. Use `calibrated_probability` if you need a probability estimate.

### Priority labels

| Score | Label |
|---|---|
| ≥ 0.70 | High Priority |
| ≥ 0.50 | Medium Priority |
| ≥ 0.35 | Low Priority |
| < 0.35 | Skip |

### Hard-rule post-processing

Leads that are structurally incompatible with the vendor profile are penalised regardless of model score:

- IT domain tender with `semantic_score < 0.20` → capped at 0.20
- Out-of-region AND `semantic_score < 0.15` → capped at 0.25

---

## Training

### Label strategy

The pipeline supports four label sources with different training weights:

| `label_source` | Training weight | When to use |
|---|---|---|
| `observed_outcome` | 1.0 | Buyer actually replied / booked a meeting / converted |
| `imported_history` | 0.8 | Historical CRM records imported in bulk |
| `human_review` | 0.4 | Sales team manually reviewed and labelled |
| `synthetic` | 0.2 | Weak supervision rules (keyword-based auto-labelling) |

Real `observed_outcome` labels always outweigh synthetic ones. **The model becomes reliable once 50+ real engagement labels are collected.**

### Train / val / test split

```text
All labeled data
├── Development set (earliest 80%)
│   └── Expanding-window time CV (5 folds, no future leakage)
└── Holdout test set (latest 20%) — never used for parameter selection
```

### Semantic scoring

Set `USE_MINILM = True` (default) to use `all-MiniLM-L6-v2` for semantic scoring (~10s load time). Set `USE_MINILM = False` to fall back to TF-IDF bigram cosine (faster, offline, lower quality).

---

## Human-in-the-Loop Feedback

Sales teams can record outreach outcomes via `create_feedback()`. Feedback is appended to `data/human_feedback.jsonl` and automatically merged into training labels on the next run.

```python
from tender_pipeline import create_feedback, append_feedback

feedback = create_feedback(
    scored_lead=result,          # output dict from score_lead()
    reviewer_id="sales_alice",
    reviewer_decision="approve",
    contacted=True,
    replied=True,
    meeting_booked=False,
    converted_to_opportunity=False,
)
append_feedback(feedback)
```

Valid `reviewer_decision` values: `approve`, `reject`, `increase_priority`, `decrease_priority`, `unsure`.

---

## Evaluation Metrics

The pipeline reports the following metrics on both validation and holdout test sets:

| Metric | Description |
|---|---|
| ROC-AUC | Overall ranking quality |
| PR-AUC | Precision-recall tradeoff (primary metric for imbalanced data) |
| Precision@K | Fraction of true positives in top-K leads |
| Recall@K | Fraction of all positives captured in top-K leads |
| Lift@K | Precision@K / positive_rate — how much better than random |
| Brier score | Calibration quality of probability outputs |

Baseline comparison includes: random, positive-rate constant, semantic-only, business-rule-only, model probability, and final priority score.

---

## Installation

```bash
pip install -r requirements.txt
```

Core dependencies: `numpy`, `scikit-learn`, `joblib`, `sentence-transformers`.

To skip MiniLM download, set `USE_MINILM = False` in `tender_pipeline.py` and run without `sentence-transformers`.

---

## Running

```bash
python3 tender_pipeline.py
```

Expected terminal output:

```text
[Load] 1500 tenders | Vendor: ...
[MiniLM] Loading all-MiniLM-L6-v2
[Lead Scoring]
[ClassWeight] Best class_weight by dev PR-AUC: ...
[Classifier Comparison] → Best classifier: ...
[Cross-Validation Summary] ...
[Calibration] Best method: ...
[Baseline Comparison Table] ...
[Top leads] ...
=== MODEL REPORT SUMMARY ===
```

---

## Running Tests

```bash
cd easy_demo
python3 -m pytest tests/test_pipeline.py -v
```

21 tests cover: time CV data leakage prevention, holdout isolation, per-fold scaler refitting, group split buyer isolation, single-class fold handling, calibration safety, baseline metric correctness, sample weight assignment, and model save/load consistency.

---

## Output

### `data/scores_output.json`

Ranked list of buyer leads. Each entry includes:

```json
{
  "tender_id": "T-00278",
  "buyer": "Vienna Municipal Services",
  "domain": "construction",
  "region": "Vienna, Austria",
  "budget_eur": 108592,
  "model_probability": 0.988,
  "calibrated_probability": 0.988,
  "business_rule_score": 0.618,
  "human_adjustment": 0.0,
  "final_priority_score": 0.98,
  "final_priority_score_100": 98.0,
  "priority": "High Priority",
  "filter_reason": null,
  "top_factors": [...],
  "email_context": {
    "buyer_name": "Vienna Municipal Services",
    "project_name": "...",
    "project_description": "...",
    "region": "Vienna, Austria",
    "budget_eur": 108592,
    "deadline_days": 45
  }
}
```

The `email_context` block is designed to be passed directly to an LLM for personalised outreach email generation.

### `models/model_report.json`

Full training report including CV results, baseline comparison, calibration metrics, selected threshold strategy, feature diagnostics, and recommended production mode.

---

## Current Performance (Weak Supervision Labels)

| Metric | Value |
|---|---|
| PR-AUC (test) | 0.60 |
| ROC-AUC (test) | 0.85 |
| Precision@10 | 0.60 |
| Recall@20 | 0.50 |
| Lift@10 | 4.6× |
| CV PR-AUC mean ± std | 0.23 ± 0.10 |
| Brier score | 0.078 |

**Caveat:** Current labels are generated by weak supervision rules (keyword matching), not real sales observations. The CV vs test gap (0.23 vs 0.60) indicates the model has learned the labelling rules rather than true buyer behaviour. Performance figures will be meaningful once 50+ real `observed_outcome` labels are collected.

---

## Limitations

1. All current training labels are synthetic (weak supervision). Real engagement data is required for reliable predictions.
2. The IT capability profile is empty — all IT-domain tenders are systematically down-scored. Populate `capability_profiles.it` to change this.
3. The CV / test PR-AUC gap (0.23 vs 0.60) indicates overfitting to the weak labelling rules.
4. `final_priority_score = 100.0` for many top leads because `model_probability` saturates at 0.96+; real data will spread scores more meaningfully.
5. Region and budget scoring relies on string matching and fixed EUR conversion rates.

---

## Roadmap

- Collect 50+ real `observed_outcome` labels via Sales feedback to make model metrics trustworthy
- Populate `capability_profiles.it` to enable IT-domain scoring
- Connect to live EU TED portal feed for automated tender ingestion
- Build a lightweight frontend dashboard consuming `scores_output.json`
- Add LLM-powered personalised email generation using `email_context` fields
- Support multiple vendor profiles for agency or multi-client use cases
