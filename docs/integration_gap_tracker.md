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
- **2026-06-21 — G6 + G7 done & live-smoked.** Capability text now uses award
  title+description (semantic 0.24→0.67–0.82 on relevant matches; P(win)
  0.27→0.79); budgets EUR-normalised via `money.to_eur` (1.353 B CZK → €54 M).
  216/216 tests; no migration / no v5 re-run (both align the app to the existing
  model). Activated via a full profile re-embed.
- **2026-06-21 — G10 done (offline-verified).** `EmailDrafter` is the single
  Claude-or-template drafting path; `EvidenceExtractor` centralises evidence; the
  `/emails` endpoints (supplier + buyer) and the agent `draft_email` tool all
  route through it. 227/227 tests (Claude path via fake client; suite forced
  offline). Live Claude smoke offered, not yet run. **Next: G9/G13** (scheduler +
  reflection wiring) or the frontend (G15/G16).
- **2026-06-22 — G13 + G9 done & live-smoked.** **G13:** real `IngestionScheduler`
  (APScheduler `BackgroundScheduler`, UTC) with 4 cron jobs (contracts daily /
  dossiers daily / awards weekly / reflect daily), opt-in via `scheduler_enabled`
  (default off → CI/tests/dev boot stay inert), wired into the FastAPI `lifespan`.
  **G9:** reflection now actuates behaviour — `Reflector.reflect()` computes
  deterministic metrics, **auto-runs the feedback→LR retrain** (the weights lever,
  reversible), and persists every cycle to the new `reflections` table (migration
  `0011`). CPV recommendations are deterministic + **advisory-only** (decision B —
  no auto-mutation of `allowed_cpv_codes`). Claude narrative when a key is present,
  deterministic fallback otherwise; `POST /agent/reflect` exposes it. 244/244
  tests (+17), ruff-clean on new code. Live smoke: scheduler registered all 4 jobs
  with correct staggered next-runs; one `reflect()` against the dev DB persisted a
  row, retrain correctly reported `insufficient` (0 feedback, no file written), CPV
  advisory = `{45: vol 9, no_signal}`, and the **Claude narrative fired live**
  (grounded, no invented numbers). **Next: frontend (G15/G16) or Understanding
  (G11/G12).**
- **2026-06-23 — G17b (recipient + threshold honesty) + a G16 follow-up bug fix.**
  **G17b:** the supplier email recipient no longer fabricates an authoritative
  `sales@<domain>` — it derives an explicitly *unverified* candidate from the
  company website (or "No verified contact on file" when there's none) and the UI
  flags it + links the website to find the real contact; the match-status "ready"
  cut-off dropped 0.8 → 0.6 to match the calibrated LR's actual win-probability
  range (the old 0.8 almost never fired, so HomeView/Matches "ready" counts read 0).
  **Bug fix (found in review, caused by G16):** the weighted re-rank path
  (`use_lr=False`) skipped the hard filter, so it scored the **entire ~15k pool and
  persisted a match row per company**; the hard filter now runs in *both* modes
  (no-ops on small/test pools). The run endpoint also now reports the *actual* mode
  (lr vs weighted) instead of assuming lr. Backend 268 tests still green; frontend
  lint + build clean.
- **2026-06-23 — Frontend awards/companies/agent UI + weight persistence (G15/G16).**
  **G15:** three new Pinia stores (`awards`/`companies`/`agent`) + views
  (`AwardsView`/`CompaniesView`/`AgentView`) + routes + nav entries (AW/CO/AG),
  each wired to the existing REST API (`/awards`, `/companies`, `/agent/run` +
  `/agent/reflect`) with the same live-API-or-sample-fallback pattern as the
  Tenders/Matches stores. **G16:** the weight sliders now persist — a new
  `weights` body on `POST /matches/run/{id}` re-ranks the tender in legacy
  weighted mode with the operator's weights (default = trained LR); `MatchesView`
  gained an "Apply weights & re-rank (save)" action that POSTs them, so overrides
  become a durable server-side re-rank (persisted to `matches.weights`) instead of
  ephemeral client state. Backend: 266 → **268 tests** (+2: weighted-mode +
  zero-weight-reject), ruff-clean. Frontend: `npm run lint` + `npm run build`
  (vue-tsc) clean. Live API smoke: `/awards` total 21,015, `/companies` 15,129,
  `/matches` 246 against the dev DB. Remaining frontend nit: G17b (real email
  recipient source).
- **2026-06-23 — Understanding layer + certification gate (pipeline completeness).**
  **G11:** `FieldExtractor` is real — Claude (evidence-constrained JSON, lazy/
  injectable client, offline fallback that builds the profile from the trustworthy
  tender columns) + `ExtractionValidator` (CPV/budget/deadline repair) +
  `understanding.service.extract_and_store_tender_profile`, persisting a structured
  `TenderProfile` to the new `tenders.tender_profile` JSONB (migration `0013`).
  Exposed via `POST /tenders/{id}/extract` and an `extract_tender_profile` agent
  tool. The trustworthy columns (CPV/title/budget/country/deadline) stay
  authoritative; Claude only adds summary/required_certifications/capabilities/
  keywords/language. **G12:** the disqualifier's cert gate now fires on the
  extracted `required_certifications` vs. each company's
  `company_profiles.certifications`, made **conservative** — it only disqualifies on
  *positive evidence* a company lacks a required cert (known cert set), never on
  absent cert data, so a tender that lists a cert can't nuke the whole pool. Inert
  in production until company-cert data exists (documented limitation, same shape
  as G9's data-limited retrain). Extracted capabilities/keywords also feed the
  legacy qualification terms. **G14:** documented the fixed-pool constraint
  (suppliers = past award winners). 246 → **266 tests** (+20: extractor/validator/
  service/disqualifier/pipeline cert gate), ruff-clean, single Alembic head `0013`.
  Matching stays cheap/deterministic — extraction is an explicit opt-in step, never
  run inside `MatchingPipeline.run`. **Manual step:** `alembic upgrade head` (0013,
  applied). **Live-verified** on the dev DB: Claude extracted a grounded profile
  from a German landscaping tender (correct CPV/summary/18-item capability list,
  `required_certifications=[]` — no hallucinated cert), persisted + round-tripped.
  See smoke record 2026-06-23.
- **2026-06-22 — tender descriptions added (matching quality + skew fix).** The
  contract-notice poller now fetches `description-proc` (BT-24); new
  `tenders.description` column (migration `0012`); the matcher folds it into the
  tender embedding text (`_tender_text`). Closes the demand-side gap vs. the
  supply side (awards already had `description`, G6) and aligns serve-time tender
  text with v5's training (`notice_title + description`), reducing train/serve
  skew. Re-poll backfilled 2986/2996 rows (100% on re-polled). 246 tests (+2),
  ruff-clean. A/B smoke (tender 917): semantic mean 0.59→0.61 + real top-5
  re-ranking; bigger lift expected where titles are generic. No retrain/re-embed
  (tenders embed on-the-fly). See smoke record 2026-06-22.

---

- **2026-06-30 — Agent hardened: streaming + resumable + caged tools (G22).** The
  Agent screen was the demo-killer (a prose-named tender → live TED poll + bulk
  dossier sweep *during a dry run* → credit drain + unkillable hang). Reworked to
  **DB-first**: `find_tender` (local lookup) → `find_matches` (deterministic
  pipeline) → grounded explanation. `download_dossiers` removed from the agent;
  `ingest_tenders`/`ingest_awards` caged (no network in dry-run; bounded +
  at-most-once live; awards gated on a zero-result `find_matches`). The loop is now
  a **streaming SSE generator** (`status`/`step`/`awaiting_input`/`final`/`error`)
  and **resumable** — conversation persisted to `agent_sessions` (migration `0014`)
  so an `ask_user` pause (tender disambiguation, incl. partial names) resumes via
  `POST /agent/run/{id}/continue`. Frontend: live activity log + disambiguation
  picker over the SSE stream. Live-smoke bug fixed: a `query_db` with a guessed
  schema poisoned the shared run transaction → wrapped it in a SAVEPOINT and made
  `find_matches` return structured top-N scores (so the model explains from real
  output, not guessed SQL). 268 → **283 tests** (+15 offline guardrail tests),
  ruff-clean, single head `0014`, frontend lint+build clean. Live-smoked (dry-run,
  real Claude): disambiguation + resume + direct-id all clean, **zero TED/portal
  calls**. **Manual step:** `alembic upgrade head` (0014, applied).
- **2026-07-01 — Agent follow-ups: public-id resolution, honest dry-run label,
  Save-results + Draft-email actions (G28).** (a) `find_tender` now resolves by the
  public **`ted_notice_id`** (e.g. `420398-2026`) too, and the Tender-detail panel
  surfaces it (styled like CPV codes) — internal db ids stay out of the UI. (b) The
  agent dry-run checkbox relabelled honestly ("Offline mode — only use
  already-ingested data") since post-rework it only gates the caged ingest tools.
  (c) **G28:** the agent result card gained **Save results** (persists the narrative +
  a server-side snapshot of the ranked matches to a new **`tender_reports`** table,
  migration `0015`, FK `tender_id`, history kept) and **Draft email** with a 🥇/🥈/🥉
  selector (pick any of the top-3 → existing `POST /emails/{match_id}/generate` → a
  "Email written with [company]" confirmation linking to the Emails screen). Plus the
  **read side**: new `GET /api/v1/emails/` list (the Emails screen had none → always
  showed sample data) wired into `EmailsView`, and a "Saved analyses" section on the
  Tender-detail panel reading `GET /tenders/{id}/reports`. 283 → **288 tests**
  (+find_tender ted-id, +3 reports, +1 emails-list), ruff-clean, single head `0015`,
  frontend lint+build clean. **Live-smoked:** save → snapshot of top-5 + list; draft
  email for the *non-top* (🥉) pick produced a real grounded Claude email; emails list
  returns 4 real drafts; reports list shows the saved snapshot. **Manual step:**
  `alembic upgrade head` (0015, applied).

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
| R20 | Feedback captured but unused / LR retraining (G8) | Step 5 | `FeedbackRetrainer` + `POST /feedback/retrain` + durable `feedback.features` (mig `0010`) |
| R21 | Thin semantic text (G6) | 2026-06-21 | capability text = award title+description; semantic 0.24→0.67–0.82 (live) |
| R22 | Budget unnormalised/sentinels (G7) | 2026-06-21 | `money.to_eur` EUR conversion + sentinel drop; CZK 1.353 B → €54 M (live) |
| R23 | Three divergent email drafters / Claude stub (G10) | 2026-06-21 | real `EmailDrafter` (Claude+fallback) + `EvidenceExtractor`; endpoint/buyer/agent unified |
| R24 | Job 4 scheduler was a stub (G13) | 2026-06-22 | `IngestionScheduler` (APScheduler, 4 cron jobs, opt-in) wired into FastAPI `lifespan`; live wiring smoke |
| R25 | Reflection narrated but didn't act (G9) | 2026-06-22 | `reflect()` auto-runs feedback→LR retrain (weights) + deterministic CPV advisory; persisted to `reflections` (mig `0011`); live-smoked |
| R26 | Understanding `FieldExtractor` was a stub (G11) | 2026-06-23 | real Claude extractor + validator + `understanding.service`; `tenders.tender_profile` JSONB (mig `0013`); `POST /tenders/{id}/extract` + agent tool |
| R27 | Cert disqualifier gate never fired (G12) | 2026-06-23 | gate fed extracted `required_certifications` vs `company_profiles.certifications`; conservative (positive-evidence only); DB-backed tests |
| R28 | Fixed supplier pool undocumented (G14) | 2026-06-23 | documented in tracker / `profile_builder` / architecture as an accepted V1 constraint |
| R29 | No UI for awards/companies/agent (G15) | 2026-06-23 | 3 Pinia stores + views + routes + nav, wired to `/awards`,`/companies`,`/agent`; live-API-or-sample fallback |
| R30 | Weight sliders cosmetic (G16) | 2026-06-23 | `POST /matches/run/{id}` accepts a `weights` body → weighted re-rank persisted to `matches.weights`; "Apply weights & re-rank" in `MatchesView` |
| R31 | Fabricated email recipient + stale ready-threshold (G17b) | 2026-06-23 | supplier contact derived from website + flagged unverified (no fake `sales@`); ready cut-off 0.8→0.6; weighted-mode hard-filter bug fixed |
| R32 | Agent loop unsafe: dry-run hit live TED/portals, hung, drained credits, no live test (G22) | 2026-06-30 | DB-first (`find_tender`→`find_matches`); `download_dossiers` removed, `ingest_*` caged (no network in dry-run; bounded + ≤1×; awards gated on zero-match); streaming SSE + resumable `ask_user` via `agent_sessions` (mig `0014`); query_db SAVEPOINT fix; +15 offline guardrail tests; live-smoked |
| R33 | No way to act on / save the agent's result; UI exposed internal ids (G28) | 2026-07-01 | `find_tender` + Tender-detail panel use public `ted_notice_id`; Save-results → `tender_reports` (mig `0015`, narrative + snapshot, history); Draft-email 🥇/🥈/🥉 selector → existing per-match endpoint; honest dry-run label; +4 tests; live-smoked |

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

#### G6 ✅ Enrich `company_profiles.capabilities.text` — DONE (2026-06-21)
`build_capability_text` now concatenates each award's `notice_title` +
`description` (capped 4000 chars, deterministic order), mirroring the v5 trainer's
company text. Live smoke: semantic cosines for relevant matches jumped from
~0.24–0.43 to **0.67–0.82** (clinic tender) and spread to **0.00–0.78** (road
tender), and P(win) for relevant matches rose from ~0.27 to ~0.79 (the LR's
strong semantic coefficient now operates on meaningful inputs — also reduces
train/serve skew vs v5). `documents.extracted_text` enrichment remains a possible
further lift. **Refs:** smoke #3, PR #10 review #4.

#### G7 ✅ Budget signal: FX-normalised + sentinels handled — DONE (2026-06-21)
New `app/matching/money.to_eur` (FX table mirroring v5's `RATES_TO_EUR`) drops
`-1`/`0` sentinels + unknown currencies. `derive_deal_size` converts award values
to EUR; the pipeline converts the tender budget (`budget_eur` + `currency`, default
EUR). Live smoke: tender 2's `1.353 B CZK` now reads **€54.12 M** (sane) and the
value features discriminate (budget 0.58–0.85, value_in_range 1.0) instead of
saturating at ~1.0. This also aligns the app with v5 (which already trains on
EUR-converted values). Residual: tenders that genuinely omit a budget still get
the 0.5 fill (data-limited). **Refs:** smoke #4 + 2026-06-21, PR #10 review #5.

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

#### G9 ✅ Reflection loop wired to behavior — DONE (2026-06-22, live-smoked)
`Reflector.reflect()` (rewritten) now computes deterministic operational metrics
(run/feedback stats), **actuates the weights lever** — auto-runs
`FeedbackRetrainer` when feedback is sufficient, writing the
`model_params_feedback.json` the pipeline auto-serves (reversible) — and persists
every cycle to the new `reflections` table (migration `0011`: `metrics` /
`actions` / `narrative`). CPV recommendations are computed deterministically
(per-division ingest-volume vs. feedback) and surfaced as **advisory** (decision
B: no auto-mutation of `allowed_cpv_codes`; `actions.cpv_applied=False`). Claude
writes the narrative when a key is configured, deterministic fallback otherwise.
`job_reflect` (G13) runs it daily; `POST /agent/reflect` triggers it on demand.
Live smoke: a cycle persisted a row, retrain correctly reported `insufficient`
(0 feedback), CPV advisory `{45: vol 9, no_signal}`, Claude narrative fired live
(grounded). **Refs:** agent review (remaining) #3.

### Priority 4 — Email generation (Phase 4)

#### G10 ✅ Real `EmailDrafter` + unified drafting paths — DONE (2026-06-21)
`EmailDrafter.draft(evidence, recipient_type)` is now the single drafting path:
Claude (`claude-sonnet-4-6` via `settings.anthropic_model`, evidence-constrained
system prompt, stable `messages.create` surface for SDK 0.39.0) with a
deterministic template fallback on missing key / SDK error / a draft that fails
`EmailValidator`. `EvidenceExtractor` centralises the evidence dict; the supplier
endpoint, buyer digest, and the agent `draft_email` tool all route through the
drafter (agent tool now fetches real evidence by `match_id` instead of a mock).
`EmailValidator` is a structural guardrail. Returns a `generator` field
(`claude`|`template`) recorded in `evidence.draft_generator`. Tests stay offline
via an autouse `_llm_available→False` fixture; the Claude path is covered with an
injected fake client. 227/227 backend tests, ruff clean. **Live-verified
2026-06-21:** with a valid key, Claude generated an evidence-grounded email for a
German tender (auto-matched language; cited only real TED number / CPV codes /
deadline). The fallback path was also exercised live (a 401 on a bad key fell
back to the template cleanly). **Refs:** backend-API #3, agent #1.

### Priority 5 — Pipeline completeness

#### G11 ✅ Understanding layer (`FieldExtractor`) — DONE (2026-06-23)
`FieldExtractor.extract_tender(raw_text, base=...)` calls Claude
(evidence-constrained JSON, lazy/injectable client, `claude-sonnet-4-6`) to enrich
a tender's text into a structured `TenderProfile` — summary, **required
certifications**, required capabilities, keywords, language — while the trustworthy
columns passed in as `base` (CPV/title/budget/country/deadline) stay authoritative
and are the whole profile when offline (deterministic fallback). `ExtractionValidator`
repairs CPV format / drops sentinel-and-implausible budgets / flags past deadlines /
dedupes lists. `understanding.service.extract_and_store_tender_profile` orchestrates
and persists to the new `tenders.tender_profile` JSONB (migration `0013`, with a
`_meta` provenance block). It is an **explicit opt-in step** —
`POST /api/v1/tenders/{id}/extract`, the `extract_tender_profile` agent tool, or a
future scheduled sweep — never run inside `MatchingPipeline.run`, so matching stays
cheap and deterministic (≤1 LLM call per tender). Offline-safe via the
`_offline_extractor` conftest fixture; Claude path tested with an injected fake
client. **Files:** `app/understanding/{extractor,validator,service}.py`,
`app/api/v1/tenders.py`, `app/agent/tools.py`. 

#### G12 ✅ Disqualifier certification gate — DONE (2026-06-23)
`pipeline.run` now feeds the tender's extracted `required_certifications` (from the
stored `tender_profile`) and each company's `company_profiles.certifications` into
`Disqualifier.check`. The gate is **conservative / closed-world only on positive
evidence**: it disqualifies a company only when we *know* its cert set (non-empty,
or `company_certifications_known=True`) and a required cert is missing — never on
*absent* company-cert data. This avoids the trap where a tender that lists a
required certification would otherwise disqualify the entire pool (no company has
cert data in the MVP). The gate is therefore **wired end-to-end and fires correctly
when company-cert data is present** (proven by DB-backed tests) but stays inert in
production until such data exists — the same "wired but data-limited" shape as G9's
retrain. A tender that was never run through extraction (`tender_profile` NULL)
keeps the prior column-only behaviour. **Refs:** PR #10 review #7; depends on G11
(done) + future company-cert data (see G14).

#### G13 ✅ Job 4 scheduler (APScheduler) — DONE (2026-06-22, live-smoked)
`IngestionScheduler` (`app/ingestion/scheduler.py`) wraps an APScheduler
`BackgroundScheduler` (UTC) with 4 cron jobs — contracts (daily),
dossiers (daily), awards (weekly, short catch-up lookback), and reflect (daily,
→ G9). Module-level job callables + `JOB_REGISTRY` + `run_job_now()` so jobs can
be fired directly (live smoke / manual / tests) without waiting on cron.
**Opt-in** via `scheduler_enabled` (default False → CI/tests/dev boot never poll
TED); wired into the FastAPI `lifespan` (starts on boot when enabled, stored on
`app.state.scheduler`, clean shutdown). The `python -m app.ingestion` CLI still
works for one-shot runs. Live wiring smoke confirmed all 4 jobs register with
correct staggered next-runs and that disabled mode is inert. **Refs:** CLAUDE.md §9.

#### G14 ✅ Supplier pool = past award winners only (fixed pool) — DOCUMENTED (2026-06-23)
`company_profiles` derive solely from companies that won past TED awards
(`profile_builder.build_company_profiles`), so a company that has never won a
listed award can never surface as a match, and company-side fields we don't get
from award data — notably **certifications** (the G12 input) — are absent. This is
an **accepted V1 constraint**, not a bug: the demand side is bounded by what TED
publishes. The lift path is Phase-5 scraped/enriched capability profiles (which
would also supply the company-cert data that activates the G12 gate in production).
Documented here, in `app/matching/profile_builder.py` (module docstring), and in
`docs/architecture.md` (deferred/known-limitations). **Refs:** PR #10 review #8,
v5 README "Known Limitations" #3.

### Priority 6 — Frontend

#### G15 ✅ UI for awards / companies / agent — DONE (2026-06-23)
Added three Pinia stores (`stores/{awards,companies,agent}.ts`) and views
(`views/{AwardsView,CompaniesView,AgentView}.vue`), registered routes, and nav
entries (AW/CO/AG) in `AppShell.vue`. Awards/Companies wire to `GET /awards` /
`GET /companies` (search + country filter, value/award rollups, source badge);
Agent wires to `POST /agent/run` (goal + dry-run → steps + output) and
`POST /agent/reflect` (metrics/actions/narrative). All follow the existing
live-API-or-sample-fallback pattern (small sample arrays added to `sampleData.ts`)
so the UI renders offline. `npm run lint` + `npm run build` (vue-tsc) clean; live
API smoke returned 21,015 awards / 15,129 companies / 246 matches from the dev DB.
**Refs:** backend-API #4.

#### G16 ✅ Weight sliders persist + re-rank — DONE (2026-06-23)
`POST /api/v1/matches/run/{tender_id}` now accepts an optional `weights` body
(`semantic`/`budget`/`location`/`qualification`); when present the pipeline runs in
legacy weighted mode (`MatchingPipeline(weights=…, use_lr=False)`) and persists the
operator's weights to `matches.weights` — so the slider overrides become a durable,
server-side re-rank instead of ephemeral client recompute (default body-less call
still uses the trained LR). `MatchesView.vue` gained an "Apply weights & re-rank
(save)" action (per selected tender); the sliders still preview live client-side.
Zero-summed weights are rejected (422). The response carries `mode`
(`lr`|`weighted`) + the applied `weights`. **Note (honest):** weighted mode
overrides the calibrated LR ranking on purpose — it's an operator review lever, not
a replacement for the model; the durable feedback that feeds G8 retraining still
comes from thumbs-up/down on the resulting matches. **Refs:** backend-API #5.

#### G17b ✅ Email recipient + match-store thresholds — DONE (2026-06-23)
`emails.ts` no longer fabricates an authoritative `sales@<domain>`: `supplierContact()`
derives an explicitly **unverified** candidate (`info@<domain>`) from the company
website, or returns "No verified contact on file" when there is no site — and the
EmailsView surfaces an "unverified contact" badge + a link to the website to find
the real contact (`EmailDraft.recipientVerified` / `companyWebsite`). Buyer outreach
keeps the real TED-published buyer org. The matches store's "ready" threshold moved
`final_score >= 0.8 → 0.6` (named `READY_SCORE`) to match the calibrated LR's actual
win-probability range — the old 0.8 essentially never fired, so HomeView's "Ready
matches" + the Matches "ready" badge read 0 even for strong matches. **Refs:**
backend-API #8.

> **Note — true verified contacts** (a real CRM/enrichment source for supplier
> emails) remain out of scope: TED award data carries none, same data limitation as
> G14. G17b makes the *absence* honest rather than inventing an address.

#### G27 🟢 In-UI command palette for ops actions ("/schedule", "/retrain") — future work
Idea (user, 2026-06-22): a text field in the UI where typing slash-commands runs
operator actions without touching code/env — e.g. `/retrain` (retrain the LR from
feedback), `/reflect` (run a reflection cycle), `/schedule on|off` (toggle the
in-process scheduler at runtime). Gives the product a more agentic feel.
- **Feasibility: HIGH; mostly already wired.** `/retrain` → existing
  `POST /api/v1/feedback/retrain`; `/reflect` → existing `POST /api/v1/agent/reflect`
  (both shipped). The only **new backend** piece is a runtime scheduler toggle:
  `IngestionScheduler.start()` currently gates on `settings.scheduler_enabled` (an
  env var read once at boot), so add e.g. `POST /api/v1/agent/scheduler {action:
  start|stop}` operating on the process-level `app.state.scheduler`, with a
  `start_now()`/`force=True` that bypasses the env gate. Frontend is a small Vue
  command field + Pinia actions mapping commands → endpoints.
- **Caveats to design in:** (a) the scheduler is **in-process per worker** — a
  runtime toggle only affects the worker that served the request (fine for
  single-worker dev; for multi-worker prod use the env flag or an external
  scheduler/lock); (b) a runtime toggle is **not persistent** across restarts
  (env `SCHEDULER_ENABLED` still governs boot); (c) these commands trigger
  **live writes / live TED polls** (esp. `/schedule on` → daily contract poll) so
  gate them (confirm step / auth once G21 lands) and surface the
  `dry_run`/`act` flags. **Refs:** builds on G13 (scheduler) + G8 (retrain) + G9
  (reflect); pairs with G15 (frontend shell).

#### G28 ✅ Act on / save the agent's result — DONE (2026-07-01)
The agent ended its run with a yes/no offer ("draft an email to the top match?") the
UI couldn't answer (the run was already `final`, not `awaiting_input`). Added two
**post-run actions** on the agent result card, plus a public-id pass:
- **Save results** → `POST /api/v1/tenders/{id}/reports` persists the narrative + a
  **server-side snapshot** of the tender's ranked matches to a new **`tender_reports`**
  table (migration `0015`, FK `tender_id`, nullable FK `session_id`, `suppliers`
  JSONB). History is kept (many per tender); the snapshot is self-contained so it
  survives a later re-match (same durability lesson as `feedback.features` / G26).
- **Draft email** with a 🥇/🥈/🥉 **selector** — the user picks any of the top-3 (they
  may disagree with the model's top pick), routed to the existing
  `POST /emails/{match_id}/generate`; a "Email written with [company]" note links to
  the Emails screen. The top-3 come from `GET /matches?tender_id=`.
- **Public-id pass:** `find_tender` resolves by `ted_notice_id` too, the Tender-detail
  panel surfaces it (styled like CPV codes), and the dry-run checkbox got an honest
  label — internal db ids stay out of the UI.
- **Read side (the save/generate write side was useless without it):** added
  **`GET /api/v1/emails/`** (list + `tender_id`/`recipient_type` filters) — the Emails
  screen had no list endpoint and always showed bundled sample data, so emails from
  the agent (or the per-match endpoint) were invisible; `EmailsView` now loads real
  drafts on mount. And a **"Saved analyses"** section on the Tender-detail panel reads
  `GET /tenders/{id}/reports` so saved agent reports are viewable (narrative + supplier
  snapshot, collapsible, per selected tender).
- **Files:** `app/db/models.py` + migration `0015`, `app/api/v1/{tenders,emails}.py`,
  `app/agent/tools.py` (ted-id resolution), `frontend/src/stores/{agent,emails,tenders}.ts`
  + `views/{AgentView,TendersView,EmailsView}.vue`. 283 → **288 tests**, live-smoked
  (save/draft + list endpoints). **Manual step:** `alembic upgrade head` (0015, applied).

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
#### G22 ✅ Agent loop unsafe + tests fully mocked — DONE (2026-06-30)
The original gap ("agent tests fully mocked, no live test") turned out to sit on top
of a much bigger defect surfaced in a live demo: a goal naming a tender in prose made
the planner call `ingest_tenders` + `download_dossiers`, and **dry-run did not stop
the network** (it only skipped DB writes) — a live TED poll + bulk portal sweep that
drained credits and hung the request unkillably. Reworked the whole agent: **DB-first**
flow (`find_tender` local lookup → `find_matches` deterministic pipeline → grounded
explanation), `download_dossiers` removed from the agent surface, `ingest_tenders` /
`ingest_awards` **caged** (no network in dry-run; bounded + at-most-once live; awards
gated on a zero-result `find_matches`). The loop is now a **streaming SSE generator**
and **resumable** — the conversation persists to `agent_sessions` (migration `0014`)
so an `ask_user` pause (tender disambiguation) resumes via
`POST /agent/run/{id}/continue`. Frontend renders the live activity log + the
disambiguation picker. The literal G22 ask is met by **+15 offline guardrail tests**
(no-network dry-run, ingest ≤1×, awards gate, ask_user pause/resume, max-turns,
bad-query-no-poison) — the valuable version asserts the guardrails, not a live API
call. Live-smoked (dry-run, real Claude): disambiguation + resume + direct-id paths
all clean, zero TED/portal calls. A live-smoke bug (a `query_db` with a guessed schema
poisoned the shared transaction) was fixed with a `begin_nested` SAVEPOINT + having
`find_matches` return structured scores. **Files:** `app/agent/{tools,controller,
progress}.py`, `app/api/v1/agent.py`, `app/db/models.py` + migration `0014`,
`frontend/src/stores/agent.ts` + `views/AgentView.vue`. **Refs:** agent review #4.
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
