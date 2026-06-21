# GTMAgent — integration gap tracker

**Single source of truth for the flags to tackle one-by-one.** Compiled
2026-06-21 after merging PR #10 (`feat/pipeline-integration-ML-backend-frontend`)
and PR #11 (`feat/lr-matching-pipeline-v5`) into `main`. This file consolidates
and **replaces** the per-branch review docs (PR #5/#7/#9/#10/#11), which have
been removed — their full text remains in git history. The `Refs:` tags below
name the originating review/PR for provenance. The only sibling doc kept is
[matching_pipeline_smoke_record.md](matching_pipeline_smoke_record.md) (live test
evidence + reproduction recipe).

Legend: 🔴 blocker · 🟠 important · 🟡 quality · 🟢 nice-to-have · ✅ resolved.

## Progress log

- **2026-06-21 — Steps 1–3 done & live-smoked.** G17 (declare `rapidfuzz`), G4
  (CPV-prefix qualification), G5 (multilingual embedder). Pool re-embedded to the
  full 15,129 profiles. Smoke: `qualification` 0→0.2–0.9, sensible Czech road
  builders ranked. See smoke record 2026-06-21.
- **2026-06-21 — Step 4 done & live-smoked.** v5 model ported into
  `app/matching/` and now serves behind the existing API/agent/frontend:
  **G1, G2, G3, G18, G26 resolved.** LR mode live (hard filter 15,129→200 → 10
  features → trained LR `predict_proba`); migration `0009`; `model_params.json`
  contract; G26 (re-match FK) fixed and live-verified. 201/201 backend tests.
  Remaining for the matcher: **G6** (thin semantic text) and **G7** (budget
  missing/unnormalised) are the visible accuracy ceilings now.
- **2026-06-21 — Step 5 done.** Feedback → LR retraining loop: **G8 resolved.**
  `feedback.features` snapshot (migration `0010`) + `match_id` SET NULL make
  feedback durable across re-matches; `FeedbackRetrainer` + `POST
  /feedback/retrain` write `model_params_feedback.json`, served in preference to
  the v5 base. 208/208 backend tests. Activate with `alembic upgrade head`.

---

## 0. The big picture in one paragraph

The application (PR #7 API + PR #5 agent + PR #10 matching/emails) is a working
**multi-supplier matchmaker**: TED ingest → `tenders`/`awards`/`companies` →
`company_profiles` (Layer 1) → `MatchingPipeline.run()` (Layer 2) → `matches` →
two-sided emails, all behind a REST API the agent can drive. **Separately**, PR
#11 produced a *much better matching model* (v5: trained LR, 10 features,
multilingual, honest Hit@3 ≈ 55%) — but it lives as a **standalone root-level
script** that reads CSVs and writes JSON, touching none of the app. **The
number-one integration task is to merge v5's model into the in-app matcher.**
Everything else is downstream of that.

---

## 1. What is RESOLVED (close these out — don't re-litigate)

| # | Item | Resolved by | Evidence |
|---|---|---|---|
| R1 | Product question: single-vendor vs multi-supplier | PR #10 | multi-supplier implemented across schema/pipeline/API/emails |
| R2 | `MatchingPipeline.run()` Phase-3 stub | PR #10 | `pipeline.py` fully implemented; smoke-recorded |
| R3 | `company_profiles` empty (no producer) | PR #10 | `profile_builder.build_company_profiles()` populates it |
| R4 | Agent `find_matches` tool dead-ends on a stub | PR #10 | tool now calls a pipeline that returns real data |
| R5 | `POST /emails/{id}/generate` referenced non-existent `Document` cols | PR #8 (pre-#10) | `_document_label()` + `extracted_text` + `downloaded_at`; real-DB test |
| R6 | `query_db` naive substring blocklist | PR #8 | word-boundary regex `_read_only_sql_error()`; tests |
| R7 | API tests were all mock-based (schema drift hid bugs) | PR #8 | `tests/test_api_real_db.py` (10 real-Postgres tests) |
| R8 | Agent: stale model id, `.bak` file, lossy days→months, no dry-run, max-turns 500 | PR #5 integration pass | all five fixed; `dry_run=True` default; graceful truncation |
| R9 | CORS hardcoded | PR #8 | `CORS_ORIGINS` setting |
| R10 | TED multi-page pagination unproven | PR #10 | full ~22.5k-notice back-fill via ITERATION token + 429 backoff |
| R11 | Awards lacked ML features (what/where/who-exactly) | PR #10 | migration `0007` (7 enrichment cols) + tax-id resolution `0008` |
| R12 | `rapidfuzz` undeclared (G17) | Step 1 | added to `requirements-ml.txt` |
| R13 | `qualification = 0` exact-CPV hole (G4) | Step 2 | CPV-prefix partial credit in `rules.py` |
| R14 | English embedder on multilingual corpus (G5) | Step 3 | default → `paraphrase-multilingual-MiniLM-L12-v2`; pool re-embedded |
| R15 | Two divergent matchers / fixed weights (G1) | Step 4 | v5 model ported into `app/matching`; LR serves behind the API |
| R16 | 10-feature ↔ schema mapping (G2) | Step 4 | migration `0009` adds 9 feature columns; legacy 4 kept as rollups |
| R17 | No hard filter / retrieval ceiling (G3) | Step 4 | v5-style hard filter in `pipeline.run` (15,129→≤200) |
| R18 | Trained-model artifact strategy (G18) | Step 4 | app loads `model_params.json` (coef+intercept+scaler); joblib not needed |
| R19 | Re-match FK crash (G26) | Step 4 | delete dependent emails before recompute; live-verified |

---

## 2. OPEN gaps — prioritized backlog

### Priority 1 — Matching model unification (the keystone)

#### G1 ✅ Merge v5's model into the in-app matcher — DONE (Step 4)
Two matchers exist: in-app (`app/matching/`, 4 fixed-weight features, DB-driven,
wired) and v5 (root script, 10 trained-LR features, CSV-driven, standalone). They
must become one: keep the in-app plumbing, adopt v5's model.
- **Plan:** (a) add CPV-4/2 + NUTS-exact/country + value-range features to
  `rules.py`; (b) load the trained coefficients from `exports/model_report.json`
  into `lr_weights.py` / `pipeline._combine` instead of `DEFAULT_WEIGHTS`; (c)
  rebuild the 10-float LR + scaler in-app (cheap) rather than shipping the joblib;
  (d) map the 10 features onto the `matches` columns or extend the schema (see G2);
  (e) make v5 the offline *training/eval* harness that regenerates coefficients.
- **Files:** `app/matching/{rules,pipeline,lr_weights,embedder}.py`,
  `exports_ml_pipeline.py`. **Refs:** v5 review #1, #4, #7.

#### G2 ✅ Resolve the 10-feature ↔ 4-column schema mismatch — DONE (Step 4, migration 0009)
`matches` has `semantic/budget/location/qualification` + `weights` JSONB; v5 has
10 features. Decide: collapse 10→4 (lossy but no migration) or add columns /
store the full feature vector in `weights` JSONB. **Refs:** v5 review #4,
`gtm_lead_scoring` gap H.

#### G3 ✅ Two-stage hard filter (retrieval ceiling) — DONE (Step 4)
v5's 26% accuracy loss is the hard filter dropping the true winner *before*
ranking. Port a DB-side hard filter (WHERE on CPV/country/value, progressive
relaxation) into `pipeline.run` — improves both speed and recall. **Refs:** v5
review #5, README "Known Limitations" #1.

#### G26 ✅ Re-matching a tender that already has an email crashes (FK violation) — DONE (Step 4, live-verified)
`pipeline.run` does an idempotent `DELETE FROM matches WHERE tender_id=X` before
re-inserting, but `emails.match_id` is a NOT-NULL FK → the delete raises
`emails_match_id_fkey ForeignKeyViolation` for any tender whose matches were
already turned into an email (the normal match → email → re-match flow).
Surfaced live on 2026-06-21 re-running tender 1. **Fix options:** delete/cascade
dependent emails first, null `emails.match_id` (needs nullable + re-anchor), or
switch the idempotency strategy from delete+insert to an upsert on
`(tender_id, company_id)`. Best handled inside the Step 4 pipeline rework.
**Refs:** Step 2/3 smoke (2026-06-21).

### Priority 2 — Scoring quality (cheap, high-leverage; can land before the full port)

#### G4 ✅ CPV-prefix matching for `qualification_score` — DONE (Step 2)
`score_qualification` matches CPV codes exactly → `qualification = 0` for every
match in the smoke run. Adopt v5's `cpv_features()` 8/4/2-digit prefix logic.
**Single highest-leverage scoring fix.** **Files:** `app/matching/rules.py`.
**Refs:** smoke #2, PR #10 review #1.

#### G5 ✅ Switch the in-app embedder to multilingual — DONE (Step 3)
`embedder.py` uses English `all-MiniLM-L6-v2`; the TED corpus is multilingual. v5
uses `paraphrase-multilingual-MiniLM-L12-v2` (also 384-d → dim-compatible).
Swap + re-encode `company_profiles.embedding`. **Files:** `app/matching/
embedder.py` + a re-embed run of `build_company_profiles`. **Refs:** PR #10
review #3.

#### G6 🟡 Enrich `company_profiles.capabilities.text`
Currently name + CPV + regions → thin semantic cosines (~0.24–0.31). Enrich from
`awards.notice_title`/`description` (now populated) and `documents.extracted_text`.
**Refs:** smoke #3, PR #10 review #4, `gtm_lead_scoring`.

#### G7 🟡 Budget signal: missing *and* unnormalised
Two distinct problems. (a) TED CNs often omit `budget_eur` → `budget_score = 0.5`
everywhere; derive from estimated-value fields / dossiers where present. (b) When
present, the value is **not FX-normalised and uses sentinels** — the 2026-06-21
smoke saw tender 2 carry `budget_eur = €1.353 B` (an un-converted/sentinel value,
the known *"contract_value_eur is not EUR-converted"* caveat), which falsely
pushed `budget_score` to ~1.0. Fix: convert to EUR via an FX table (v5's
`RATES_TO_EUR` is reusable) and treat `-1`/`0`/implausible magnitudes as missing.
**Refs:** smoke #4 + 2026-06-21 re-run, PR #10 review #5, exports/README data caveats.

### Priority 3 — Feedback loop / self-improvement (Phase 5)

#### G8 ✅ `lr_weights.py` retraining — DONE (Step 5)
`FeedbackRetrainer` fits an LR on `(feedback.features, rating)` pairs and writes
`model_params_feedback.json`, which `LogisticRegressionScorer.load_active()`
serves in preference to the v5 base (delete the file to revert). Feedback is made
durable across re-matches: `feedback.features` snapshots the match's 10-feature
vector at submit time (migration `0010`), and `feedback.match_id` → nullable +
`ON DELETE SET NULL` (same fix class as G26). Endpoint: `POST /feedback/retrain?
min_samples=N` (guarded: needs ≥N rows and both classes, else keeps the base
model). **Refs:** PR #10 review #2, backend-API #6, agent #3.
**Caveat:** the feedback model is feedback-only (not blended with the v5 base),
so it's illustrative until enough ratings accumulate — raise `min_samples` or
delete the file to fall back to v5. Blending v5 + feedback is a future option.

#### G9 🟡 Reflection loop is built but not wired to behavior
`reflector.py` narrates recent runs/feedback but nothing reads its output back
into the weights/CPV filters, and there's no scheduler hook. Naturally sequenced
after G8 + the scheduler (G13). **Refs:** agent review (remaining) #3.

### Priority 4 — Email generation (Phase 4)

#### G10 🟠 Make `EmailDrafter` real and unify three drafting paths
Three drafters exist and don't agree: deterministic endpoint templates
(`_draft_from_evidence` / `_draft_buyer_email`, real), `generation/drafter.py`
(Claude, stub), and the agent's `draft_email` tool (calls the stub → errors).
Make `EmailDrafter` the real Claude implementation (model `claude-sonnet-4-6`,
evidence-grounded), route the endpoint + agent tool + deterministic fallback
through it. **Files:** `app/generation/{drafter,evidence,validator}.py`,
`api/v1/emails.py`, `agent/tools.py`. **Refs:** backend-API #3, agent #1.

### Priority 5 — Pipeline completeness

#### G11 🟡 Understanding layer (`FieldExtractor`) is a stub
No structured `TenderProfile`; the matcher reads tender columns + dossier text
directly. Blocks the disqualifier's certification gate (G12) and richer
qualification matching. **Files:** `app/understanding/{extractor,validator}.py`.
**Refs:** CLAUDE.md §9 Phase 2.

#### G12 🟡 Disqualifier certification gate never fires
`pipeline.run` passes `required_certifications=[]` / `company_certifications=[]`,
so only the budget-capacity gate is live. Depends on G11 (structured cert
requirements) + cert data on `company_profiles`. **Refs:** PR #10 review #7.

#### G13 🟡 Job 4 scheduler (APScheduler) is a stub
Ingestion runs via the `python -m app.ingestion` CLI only; `scheduler.py` is a
stub. Needed before the reflection loop (G9) can run on a cadence. **Refs:**
CLAUDE.md §9.

#### G14 🟢 Supplier pool = past award winners only (fixed pool)
`company_profiles` derive solely from companies that won past awards; an unseen
company can never match. Lift later via Phase-5 scraped capability profiles
(the "demand side"). Acceptable V1 constraint — document it. **Refs:** PR #10
review #8, v5 README "Known Limitations" #3.

### Priority 6 — Frontend

#### G15 🟡 No UI for awards / companies / agent
`/awards`, `/companies`, `/agent/run` work at the API level but have no Pinia
stores or views; nav is only Command/Tenders/Matches/Emails. **Refs:**
backend-API #4.

#### G16 🟡 Weight sliders are cosmetic
`MatchesView.vue` recomputes scores client-side only; nothing POSTs back, so
overrides can't feed G8's retraining. Needs a persistence endpoint
(`PATCH /matches/{id}/weights` or per-tender weights). **Refs:** backend-API #5.

#### G17b 🟢 Email recipient + match-store thresholds are placeholders
`emails.ts:recipientFor()` fabricates `sales@<website-domain>` as the recipient —
real outreach needs a real contact source. The matches store maps
`final_score >= 0.8` → "ready"; confirm that threshold/field lines up with what
the unified pipeline actually writes (G1). **Refs:** backend-API #8 (minor).

### Priority 7 — Dependencies, artifacts, hygiene

#### G17 ✅ `rapidfuzz` undeclared — DONE (Step 1)
`exports_ml_pipeline.py` imports `rapidfuzz`; it's in no requirements file →
fresh-checkout `ImportError`. Add to `requirements-ml.txt`. **One-line fix.**
**Refs:** v5 review #2.

#### G18 ✅ Trained model artifact / strategy — DONE (Step 4: app loads model_params.json)
`exports/company_matcher.joblib` is generated, not in git. Prefer rebuilding the
10-float LR from `model_report.json` coefficients in-app over committing a
version-coupled joblib (decide as part of G1). **Refs:** v5 review #3.

#### G19 🟢 Large generated artifacts in git
`exports/top3_results.json` (20k lines), `exports/gtm_awards_export.zip` (8.3 MB),
`exports/awards_training.csv` (21k rows) — no `.gitignore` rule. Keep a frozen
training snapshot for the report; gitignore regenerated outputs. **Refs:** PR #10
review #10, v5 review #9, `gtm_lead_scoring` gap A.

#### G20 🟡 Feature logic in two places (accepted train/serve split after Step 4)
Step 4 settled v5↔app as **v5 = offline trainer, app = server**: the 10-feature
math now exists in both `exports_ml_pipeline.py` (training) and
`app/matching/features.py` (serving), intentionally separate but **must stay in
sync** — change v5's features → port to `features.py` → regenerate
`model_params.json`. Name normalisation / profile building / FX table are still
duplicated too. Lower priority now the serving path is unified; revisit if the
two feature implementations drift. **Refs:** v5 review #7.

### Priority 8 — Later / out of V1 scope

#### G21 🟢 Auth / multi-tenant — Phase 5, not started.
#### G22 🟢 Agent tests fully mocked (no live-API CI test) — agent review #4.
#### G23 🟢 v5 model trained on 50% of data — retrain on more once ported (v5 #6, #8).
#### G24 🟢 PDF portal scraping deferred (per `docs/Notes.md`) — adapter registry + Firecrawl/Claude fallback if/when needed.
#### G25 🟢 `backend/easy_demo/` is doubly superseded — decide its fate
The seller-perspective lead-scoring spike was first ported into `app/matching/`,
then superseded as the ML model by v5. Its own gaps (tests not in CI, non-package
layout, `joblib` undeclared in its `requirements.txt`, vendor-hardcoded
constants, all-synthetic data, committed `.joblib`/`scores_output.json`
artifacts) are not worth fixing if it's dead. **Decide:** archive/remove it, or
keep it as a documented standalone demo. **Refs:** gtm_lead_scoring gaps B/D/E/F/G.

---

## 3. Recommended attack order (first sprint)

1. **G17** (declare `rapidfuzz`) — trivial, unblocks running v5.
2. **G4 + G5** (CPV-prefix qualification + multilingual embedder) — small, in-app,
   high-leverage; don't need the full port. Re-run the smoke to confirm
   `qualification > 0` and better semantic spread.
3. **G1 + G2 + G3** (the model unification: features, schema mapping, hard
   filter, trained weights) — the keystone. Land it behind the existing
   `POST /matches/run/{id}` so the API/agent/frontend pick it up for free.
4. **G8** (wire `lr_weights.py` to feedback) — turns the captured feedback into a
   live retraining loop using the same feature vectors.
5. **G10** (real `EmailDrafter`, unify drafters) — completes Phase 4.
6. Then the completeness/UI items (G6, G7, G11–G16) and hygiene (G18–G20).

> **Key insight for the report:** PR #10 made the pipeline *work*; PR #11 made the
> model *good*. They were built on separate tracks and currently don't touch each
> other. The integration story — porting the v5 model into the live pipeline so
> the API/agent/frontend serve honest Hit@3 ≈ 55% predictions instead of fixed
> 0.40/0.20/0.20/0.20 guesses — is both the biggest remaining technical task and
> the most compelling thing to demo.
