# Branch review — `feat/easy-demo` (Shihao / Gina)

Merged to `main` via PR #6 (`96496d4`, 2026-06-08). Adds a single
self-contained folder: `backend/easy_demo/` (`tender_pipeline.py`,
`requirements.txt`, `README.md`, `data/{tenders.json, company_profile.json}`).
Nothing else in the repo was touched — it does not import from `app.*` and
is not wired into FastAPI, Alembic, or CI.

## What it actually is

A standalone runnable script (`python3 tender_pipeline.py`) that proves out
the **Phase 3 matching algorithm end-to-end on hand-curated JSON**, no DB
involved:

1. Loads one `company_profile.json` (single company) and a list of
   `tenders.json` (3 sample tenders — interestingly, real TED notice IDs
   from our own ingested data, e.g. `TED-326509-2026`, repurposed as demo
   fixtures with hand-assigned `domain` / `result` labels).
2. **Semantic scoring** (`SemanticScorer`): encodes the company's
   `capability_profiles` (one text blob per `construction` / `it` / `hybrid`
   "domain") with MiniLM (`all-MiniLM-L6-v2`, falls back to TF-IDF cosine if
   `USE_MINILM = False`), embeds each tender's `project_description`,
   cosine-similarity against the matching domain's company embedding, maps
   raw cosine into `[0, 1]`.
3. **Rule scoring**: `score_budget` (ratio if outside company's
   `budget_range_wan`, else 1.0), `score_region` (substring match → 1.0 else
   0.3), `score_qualification` (≥2-keyword overlap after stripping filler
   words like "及以上"/"认证"), `score_deadline` (`days / 60`, clipped).
4. **Feature vector**: `[semantic, budget_match, region_match, qual_match,
   days_norm]` per tender.
5. **Dual-domain Logistic Regression** (`DomainLR` / `TenderMatcher`):
   trains *separate* `StandardScaler → LogisticRegression` pipelines for
   `construction` and `it`, with `hybrid` tenders folded into both training
   sets; blends `p_construction`/`p_it` 50/50 for hybrid tenders at
   inference. Falls back to a flat feature-mean if <2 labeled samples.
6. **Explainability**: `DomainLR.explain()` ranks features by
   `scaled_value × LR_coefficient`, returns signed top-N "contributions" —
   this is effectively the `explanation` string format our `matches` table
   is supposed to carry.
7. **Manual weight adjustment simulation** (`interactive_adjust`): takes the
   LR-recommended weights, simulates a "Sales" rep boosting
   `semantic_score` to 0.50 and renormalizing, prints a default-vs-adjusted
   score comparison.
8. Writes everything to `data/scores_output.json` for dashboard consumption.

## Why this matters for our phases

This is a **working reference implementation of exactly the architecture
CLAUDE.md §1 commits us to**: "hybrid score = semantic embedding cosine +
rule-based sub-scores + LR-learned weights [+ manual override via
feedback]". Phase 3 in our codebase (`app/matching/*`) is currently five
files of pure stubs (`pipeline.py`, `embedder.py`, `semantic.py`,
`rules.py`, `lr_weights.py` all end in `...`/`TODO: Phase 3`). This script
is proof the approach works and gives us concrete code to port from rather
than designing from scratch.

## What works / is directly reusable

- **The scoring pipeline shape is right**: semantic + 4 rule sub-scores →
  feature vector → LR → probability → label. Maps cleanly onto
  `MatchingPipeline.run()`'s documented flow (disqualify → embed/score →
  rules → weighted combine → persist).
- **Explainability pattern** (`top_factors`: feature, value, signed
  contribution, direction) is a ready template for the `matches.explanation`
  TEXT column — it's already in the exact "evidence-grounded" spirit Phase 4
  needs for email drafting.
- **Recommendation-label thresholds** (`≥0.70` Strongly Recommend, `≥0.50`
  Recommend, `≥0.35` Consider, else Not Recommended) are a sane starting
  point for any UI score-bucket display.
- **Manual weight override simulation** maps conceptually onto the
  feedback-driven LR retraining loop (`lr_weights.py`, Phase 5) and could
  inspire a "sales override" UI affordance later.

## Gaps — what has to change before this becomes our Phase 3

1. **Not wired to the app at all.** It reads/writes flat JSON files, not
   `tenders` / `company_profiles` / `matches` tables, and isn't reachable
   via FastAPI. Porting means rewriting it against `app/db/models.py` ORM
   objects and `app/understanding/schemas.py` (`TenderProfile`,
   `CompanyProfile`) — and actually filling in `app/matching/pipeline.py`,
   `embedder.py`, `semantic.py`, `rules.py`, `lr_weights.py`.
2. **Single hardcoded company.** The demo is "one company scans many
   tenders"; our `MatchingPipeline.run(tender_id)` is the inverse — "one
   tender ranks many companies from `company_profiles`". The scoring math
   transfers, but the iteration direction and the company-pool query do
   not — this needs a deliberate redesign, not a copy-paste.
3. **Single embedding model vs. our locked ensemble.** CLAUDE.md commits to
   an `EnsembleEmbedder` (MiniLM 384d + mpnet 768d + multilingual-e5-large
   1024d, lazy-loaded, CPU-only) feeding `company_profiles.embedding
   Vector(384)` and the generic `embeddings.vector Vector(768)`. The demo
   uses one model (MiniLM or TF-IDF) and a single cosine score — needs
   extension to ensemble averaging or a documented decision to simplify our
   locked plan down to match the demo (the latter would be a real
   architecture conversation, not a unilateral code change).
4. **"Domain" (`construction` / `it` / `hybrid`) doesn't exist in our
   schema.** The demo's whole dual-LR-model design hinges on this tag, which
   is hand-assigned per tender in the JSON fixture. Our `TenderProfile` has
   `cpv_code` / `required_capabilities` / `keywords`; `CompanyProfile` has a
   flat `capabilities: list[str]`, no domain-keyed text blobs. Before
   porting the dual-LR split we need to decide: derive "domain" from CPV
   code ranges, drop the split for a single combined LR model (simpler,
   matches `lr_weights.py`'s singular `LogisticRegressionWeightLearner`
   design), or introduce a domain-tagging step in the extractor.
5. **LR training labels.** The demo trains on a hand-baked `result: 0|1`
   field inside `tenders.json`. Production labels are supposed to come from
   the `feedback` table (thumbs-up/down → retrain), per
   `lr_weights.py`'s own `TODO: Phase 5 — load (features, label) rows from
   feedback table`. With effectively zero feedback rows at the start, the
   "insufficient samples → fall back to feature mean" branch in `DomainLR`
   is actually the realistic cold-start path — worth keeping that fallback
   logic when porting.
6. **Rule scorers are intentionally simplistic placeholders** (substring
   region match, ≥2-keyword qualification overlap, linear budget ratio) —
   acceptable for a demo, but `RuleScorer`/`Disqualifier` in our codebase
   are meant to operate on typed `CompanyProfile`/`TenderProfile` objects
   with harder gates (missing certification, excluded country, size
   threshold) — a stricter rewrite is needed, not just a port.
7. **Currency**: only handles `budget_cny_wan` (CNY in units of 万 = 10k).
   Our tenders carry EUR/DKK/CZK/etc (`tenders.budget_eur`,
   `tenders.currency`). The demo's own README §11 already flags this as a
   known limitation — needs real currency normalization before the
   `budget_match` sub-score is meaningful on our data.
8. **No persistence** — `MatchingPipeline.run()` is documented to write
   `final_score` / 4 sub-scores / `weights` JSONB / `explanation` /
   `is_disqualified` rows to `matches`; the demo only writes a JSON file.
9. **`requirements.txt`** lists only `numpy`, `scikit-learn`,
   `sentence-transformers` — doesn't account for the 3-model ensemble
   footprint or pgvector storage our locked stack requires.
10. Bilingual (Chinese/English) README and print statements — fine for
    understanding intent during the port, but would need cleanup/translation
    before this becomes mainline documentation.

## Suggested next step

Treat this as a **spike to port from, not code to merge in place**: pull the
scoring math (semantic mapping curve, rule sub-scores, LR + explain pattern,
label thresholds) into `app/matching/{semantic,rules,lr_weights}.py`, redesign
the iteration direction and embedder around our actual schema/ensemble, and
decide the "domain" question before committing to the dual-LR-model split.
