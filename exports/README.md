# exports/

Holds the **one ML artifact the running application depends on**:

- `model_params.json` — the v5 logistic-regression matcher's parameters
  (feature names + coefficients + intercept + StandardScaler mean/scale).
  The app loads it at runtime via `app/matching/lr_weights.py`
  (`repo-root/exports/model_params.json`). At runtime, feedback retraining may
  additionally write `model_params_feedback.json` here, which the matcher
  prefers when present (delete it to revert to the base model).

Regenerate `model_params.json` with the trainer:

```
py -3 run_pipeline.py        # see README_ML_PIPELINE.md
```

The bulky training **inputs** (`awards_training.csv`, `companies.csv`) and
trainer **byproducts** (`top3_results.json`, `model_report.json`,
`company_matcher.joblib`, …) are not needed to run the app and live under
[archive/data-exports/](../archive/data-exports/) — that folder's README
documents the dataset columns and caveats.
