# Branch review — `feat/gtm-lead-scoring-v2` (ML lead-scoring rewrite)

The full rewrite of the former `feat/easy-demo` spike (commit `34c22f2`,
"rebuild easy_demo as GTM lead scoring pipeline"). `backend/easy_demo/` went
from a 407-line single script to a ~2,500-line package (`tender_pipeline.py`
1,131 lines + `evaluation.py`, `baselines.py`, `cross_validation.py`,
`calibration.py`, `diagnostics.py`, a 493-line pytest suite, a trained model
artifact, and regenerated data).

**This document supersedes `docs/branch_review_easy_demo.md`** (deleted): the
old gap list is carried forward below with each item marked resolved /
partial / open against the new code.

> **Headline.** Engineering quality jumped a lot — this is now a *rigorous* ML
> pipeline (chronological/expanding-window CV with leakage guards, probability
> calibration, baseline comparison, holdout isolation, class-weight & classifier
> search, label-source weighting, human-in-the-loop feedback). But its
> **integration distance to the app grew, not shrank**, and it embeds a
> **product-model decision that conflicts with the rest of the codebase**
> (single-vendor → rank buyers, vs. the DB/API's tender → rank many supplier
> `company_profiles`). That perspective question must be settled before any
> port into `app/matching/` — it decides whether this maps onto the `matches`
> table at all.

---

## What it is now

A **seller-perspective lead-scoring pipeline**: given **one** vendor profile
(`company_profile.json`, currently Bembé Parkett) and a feed of tenders, it
ranks the *buyers* (tender issuers) as sales leads and emits an
`email_context` block per buyer for outreach.

Pipeline (all in `backend/easy_demo/`, standalone, no `app.*` imports):

1. **5 features** per tender: `semantic_score` (MiniLM cosine, vendor
   capability vs buyer description, `normalize_embeddings=True`; TF-IDF bigram
   fallback), `budget_score` (EUR-converted vs target deal size, range decay),
   `region_score` (substring match, 1.0/0.2), `urgency_score` (deadline
   sweet-spot window), `competition_score` (1/received_tenders).
2. **Label strategy**: `engagement ∈ {0,1}` + `label_source`
   (`observed_outcome` 1.0 / `imported_history` 0.8 / `human_review` 0.4 /
   `synthetic` 0.2) → per-sample training weights.
3. **Model selection**: class-weight comparison, classifier search
   (LR / RandomForest / HistGradientBoosting by PR-AUC), expanding-window
   time-series CV (leakage-guarded), sigmoid/isotonic calibration, holdout
   test (latest 20%, never used for selection).
4. **Final priority score** = `α·model_prob + β·business_rule_score +
   human_adjustment + German-market bonus`, then **hard-rule post-processing**
   (IT-domain & out-of-region penalties), bucketed into High/Medium/Low/Skip.
5. **Persistence**: trained `ModelBundle` → `joblib`; metrics → JSON reports;
   ranked leads → `scores_output.json`.
6. **Feedback**: `create_feedback()/append_feedback()` → `human_feedback.jsonl`
   → merged into labels on the next run.

---

## Integration quality & adaptability

**Integration today: zero.** `grep` confirms nothing in `app/` or `tests/`
imports `easy_demo`; `app/matching/*` are still Phase-3 stubs. It reads/writes
flat files and a joblib artifact, runs as a CLI (`python tender_pipeline.py`),
and uses **bare cwd-relative imports** (`from evaluation import …` inside a
`try/except ImportError`) — so it only runs from inside `easy_demo/`. Porting
into `app.matching` means repackaging every module.

**Adaptability — what ports cleanly vs. what fights the schema:**

*Reusable as-is (high value):* the rule sub-scorers (budget/urgency/competition
math), the MiniLM cosine + `[0,1]` mapping, the explainability format
(`top_factors`: feature/value/contribution/direction → ready for
`matches.explanation`), the `email_context` block (drops straight into the
Phase-4 drafter), the label-source weighting idea, and especially the
**evaluation rigor** (CV/calibration/baselines/holdout) — none of which the
production stubs have.

*Fights the current data model:*
- **Perspective inversion (the big one).** This ranks **buyers for one vendor**;
  the `matches` table (`tender_id` + `company_id → company_profiles`) and the
  backend `/matches` + `/emails` flow rank **many supplier `company_profiles`
  for one tender**, and draft outreach *to the supplier*. These are two
  different GTM products. CLAUDE.md §1/§4 commit to the multi-supplier model
  ("match against a curated CompanyProfile pool… the demand side"); this branch
  implements the single-vendor model. They cannot both be right — **resolve
  this before porting.**
- **Feature mismatch.** ML has 5 features (semantic/budget/region/urgency/
  competition); `Match` has 4 (semantic/budget/**location**/**qualification**).
  `urgency`/`competition` have no column; `qualification` isn't computed here.
  (`weights` JSONB could absorb extras, but it needs a deliberate mapping.)
- **`domain` (construction/it/hybrid)** still doesn't exist in our schema —
  it's hand-assigned in the JSON and drives the dual-capability semantic match
  + the IT hard-filter. `TenderProfile` has `cpv_code`/`keywords` instead.
- **Single embedding model**, not the locked ensemble (MiniLM 384 + mpnet 768 +
  e5 1024) feeding pgvector. No pgvector use at all.
- **Parallel feedback store.** Human feedback goes to `human_feedback.jsonl`,
  not the `feedback` table the API already writes to (Phase 5). Two feedback
  paths that would have to reconcile.
- **Vendor-specific constants baked into code** (hardcoded German
  `PRIMARY_REGIONS` bonus, fixed FX rates, α/β, IT filter tuned to Bembé) —
  not config, not multi-tenant.

---

## Old gaps (from `branch_review_easy_demo.md`) — status against the rewrite

| # | Old gap | Status |
|---|---|---|
| 1 | Not wired to the app (flat JSON, no FastAPI/DB) | 🔴 **Open** — still standalone; arguably *more* so (own model artifacts, deps, CLI) |
| 2 | Single company; iteration direction is the inverse of `MatchingPipeline.run(tender_id)` | 🔴 **Open & now a formal design stance** — seller→buyers is intentional here; conflicts with the DB/API model |
| 3 | Single embedding model vs. locked ensemble | 🔴 **Open** — still single MiniLM/TF-IDF, no pgvector |
| 4 | `domain` tag doesn't exist in our schema | 🔴 **Open** — still hand-assigned, still load-bearing (semantic + IT filter) |
| 5 | LR labels are hand-baked `result` | 🟡 **Framework resolved** — label_source weighting + feedback loop; **but** all real labels are still synthetic, and the loop targets a JSONL file, not the `feedback` table |
| 6 | Rule scorers are simplistic placeholders | 🟡 **Much improved** — EUR budget decay, urgency sweet-spot, competition, hard-rules; **but** added vendor-specific hardcoding (new gap G), still string-match region |
| 7 | Currency only handles CNY (万) | ✅ **Resolved** — EUR with FX table (DKK/GBP/USD); FX rates hardcoded (minor) |
| 8 | No persistence (JSON only) | 🟡 **Partial** — now persists model (joblib) + reports; still **not** the `matches` table |
| 9 | `requirements.txt` minimal, ignores ensemble/pgvector | 🟡 **Partial** — adds sklearn/sentence-transformers; **`joblib` is imported but missing from requirements.txt** (real bug); still no pgvector; app `requirements.txt` unchanged |
| 10 | Bilingual README & prints | 🟡 **Mostly resolved** — README & prints now English; `tender_pipeline.py` module docstring (lines 4–13) is still Chinese |

---

## New gaps introduced by the rewrite

- **A. Large/binary artifacts committed to git.** `lead_scoring_pipeline.joblib`
  (368 KB binary), `scores_output.json` (1.5 MB / 43k lines), `tenders.json`
  (868 KB / 1,500 rows), plus several report JSONs. Bloats the repo, churns on
  every regeneration (merge-conflict magnet), and the joblib is version-coupled
  to the exact sklearn version + the `ModelBundle`/module layout (brittle to
  load elsewhere). Recommend `.gitignore` for generated artifacts; treat the
  model as a build output, not source.
- **B. All training data is synthetic (weak supervision).** `tenders.json` is
  1,500 fabricated rows (mismatched buyer/region, generic descriptions) with
  keyword-rule labels. The README itself flags the CV↔holdout gap (PR-AUC ≈0.23
  CV vs ≈0.59 test = overfitting to the labelling rules). **Metrics are not yet
  meaningful**; the model is a scaffold pending ~50+ real `observed_outcome`
  labels.
- **C. Feedback duplication.** `human_feedback.jsonl` vs. the DB `feedback`
  table — two stores with different shapes; must be reconciled with the Phase-5
  loop if integrated.
- **D. Its 21 tests never run in CI.** `pyproject` sets `testpaths = ["tests"]`,
  so `backend/easy_demo/tests/` is excluded; the suite also needs `sys.path`
  hacks + cwd=`easy_demo`. Real coverage of the ML logic exists but gates
  nothing.
- **E. Non-package module layout** (bare `from evaluation import …`) — won't
  import as `app.matching.*` without restructuring.
- **F. `joblib` import not declared** in `easy_demo/requirements.txt` (fresh
  install → `ImportError`).
- **G. Vendor-specific business logic hardcoded** (German market bonus, FX
  rates, IT filter, α/β) rather than configurable — blocks multi-vendor use and
  is tuned to the one Bembé profile.
- **H. `matches`-table feature mismatch** (5 ML features vs. 4 ORM columns; no
  `qualification`, extra `urgency`/`competition`).

---

## Verdict & recommendation for Gap #2

This is a **strong spike to port from** — substantially more production-minded
than the old demo on the modelling side (CV, calibration, evaluation,
feedback). But it is **not** drop-in, and the gap to the app is mostly
*structural and conceptual*, not algorithmic.

**Before writing `MatchingPipeline.run()`, settle one product question:**
is GTMAgent (a) a **single-vendor** lead tool (rank buyers for one company — what
this branch built), or (b) a **multi-supplier** matchmaker (rank many
`company_profiles` per tender — what the schema, `/matches`, `/emails`, and
CLAUDE.md describe)? The answer determines:
- whether the iteration direction inverts on port,
- whether output rows fit `matches` (tender_id + company_id) at all,
- who the email is addressed to (buyer vs. supplier),
- whether `company_profiles` is one row or a pool.

Once that's decided, port the **scoring math + evaluation harness + email_context
+ explainability**, map features onto the `matches` schema (or extend it
deliberately), swap the JSONL feedback for the `feedback` table, and gitignore
the generated artifacts. Until the perspective question is answered, plugging
this into `app/matching/` risks building the wrong product cleanly.

See also: [branch_review_backend_api.md](branch_review_backend_api.md) (the
`/matches` + `/emails` consumer that's waiting on a producer) and
[branch_review_agent_controller.md](branch_review_agent_controller.md) (the
agent's `find_matches` tool, also waiting on `MatchingPipeline.run()`).
