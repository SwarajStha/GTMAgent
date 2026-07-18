# Tender → Company Matching Pipeline

Given a new EU procurement tender, ranks the top 3 most suitable companies from a fixed catalog of 14,066 companies.

## How It Works

**Two-stage pipeline:**

1. **Hard Filter** — narrows 14,066 companies down to ≤200 candidates using CPV code, buyer country, and contract value. Progressively relaxes criteria (CPV-4 + country + value → CPV-2 + country → CPV-2 only → country only → all companies).

2. **Logistic Regression Ranker** — scores each candidate on 10 features and ranks by predicted win probability.

### Features Used

| Feature | Description |
|---|---|
| `semantic_score` | MiniLM cosine similarity between tender text and company profile |
| `cpv_4digit_score` | 4-digit CPV code match |
| `cpv_2digit_score` | 2-digit CPV code match |
| `nuts_exact_score` | NUTS-2 region exact match |
| `nuts_country_score` | Country-level NUTS match |
| `value_score` | Log proximity of tender value to company's historical median |
| `value_in_range_score` | Whether tender value falls within company's historical range |
| `country_match_score` | Buyer country matches company's historical winner countries |
| `company_size_score` | Company activity (log-scaled award count) |
| `competition_score` | Fixed at 0.5 (n_offers unknown at prediction time) |

### Company Profiles

Each company profile is built from its full award history:
- **Text**: concatenated tender titles and descriptions (up to 4,000 chars), encoded with `paraphrase-multilingual-MiniLM-L12-v2`
- **Structured**: CPV codes, NUTS codes, countries, contract value statistics (median, min, max)

## Results

Evaluated on 500 held-out tenders (honest evaluation — no pre-filtering, winner not forced into candidate pool):

| Metric | Value |
|---|---|
| Hit@1 | 45.4% |
| Hit@3 | 54.8% |
| Hit@5 | 59.2% |
| Winner filtered out by Stage 1 | 26.2% (131/500) |
| Winner unresolvable | 0% |

**Note:** 26% of tenders have their true winner removed by the hard filter before LR ever runs. Among tenders where the winner survives Stage 1, Hit@3 is ~74%.

## Data

- `archive/data-exports/awards_training.csv` — 21,015 historical EU procurement awards
- Chronological train/test split (leakage-safe); hard negatives: 5 per positive,
  sampled from the same country + CPV + value band

> The bulky training inputs live under `archive/data-exports/` (see
> `archive/README.md`); only `exports/model_params.json` — the artifact the
> running app loads — stays in `exports/`.

## Run

```
py -3 run_pipeline.py
```

Outputs:
- `exports/model_params.json` — **the runtime artifact** the app's matcher loads
  (LR coefficients + intercept + scaler)
- `archive/data-exports/top3_results.json` — per-tender predictions
- `archive/data-exports/model_report.json` — metrics and LR coefficients
- `archive/data-exports/company_matcher.joblib` — saved model + scaler

## Known Limitations

1. **Hard filter miss rate (26%)** — winners whose CPV/country combination has no historical match get filtered before LR can rank them
2. **Structured feature leakage** — company profiles include all historical awards; for training pairs, the current tender's CPV/NUTS/country contribution is not excluded from structured features
3. **Fixed company pool** — pipeline assumes all possible winners are already in the 14,066-company catalog
