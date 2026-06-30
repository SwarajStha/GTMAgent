# Project Notes

Two parts:
1. **Incremental Improvement Log (gap-driven)** — the dated find-a-gap → fix →
   verify history, for report writing.
2. **Future Decisions (design rationale)** — the architecture decisions and their
   rationale, at the end.

---

# Incremental Improvement Log (gap-driven)

> **Purpose.** A dated, chronological record of how the project was improved
> incrementally — each entry states the *trigger* (usually a PR merge or a live
> smoke), the *gaps found*, the *fixes made*, and how they were *verified*. Built
> for report writing: it shows the find-a-gap → fix → verify loop over time.
> Sources: `CLAUDE.md` session log (§13), git history, the per-branch reviews
> (consolidated into `docs/integration_gap_tracker.md`), and
> `docs/matching_pipeline_smoke_record.md`. Entries before 2026-06-21 are
> reconstructed from those records; the 2026-06-21 entries were logged live.

The gap IDs (G1–G26, R1–R23) referenced below are defined in
`docs/integration_gap_tracker.md` — the single backlog/closure tracker.

---

## 2026-05-13 — Phase 1 scaffold + same-day hardening
- **Built:** full repo skeleton (FastAPI backend, Vue 3 frontend, Docker compose,
  CI, Alembic baseline `0001`), 28/28 stub tests green.
- **Gaps found + fixed the same day:** (1) host Postgres squatting on port 5432 hid
  Docker's DB → demoted the Windows service to Manual; (2) `npm install`
  deprecation warnings → migrated to ESLint 9 flat config; (3) Vite proxy didn't
  forward `/health` → fixed. Established the env quirks that recur (Python 3.11
  via `py -3.11`, local pip `--trusted-host` SSL workaround).

## 2026-05-15 → 16 — Phase 2 / Job 1: TED Contract Notice poller
- **Built:** `TedClient` (primary/secondary endpoint + transport retry +
  truststore SSL), `TenderRow` parser, Postgres `xmax=0` upsert; 5 live tenders.
- **Gap found (live vs docs):** the Job-1 spec's TED field names were pre-eForms
  and **rejected by the live v3 API** (HTTP 400). Iterated 4 rounds against the
  live API to discover the real eForms vocabulary (`classification-cpv`,
  `notice-title`, …) and that `cn-light` is rejected. **Lesson captured:** trust
  live API evidence over older docs — reused on every later TED field change.
- **Verified:** first run `{new:5}`, second `{updated:5}` → upsert + xmax detection.

## 2026-05-16 → 17 — Job 2 (awards + entity resolution) & Job 3 (dossiers + CLI)
- **Job 2:** awards back-fill (`can-*` → `awards` + `companies`) with
  `normalise_name` + `resolve_or_create` entity resolution. **Gap (round 1):**
  spec winner-name fields never populate on live TED; **round 2 fix:** reordered
  the fallback chain to `organisation-name-tenderer` (always populated on
  `selec-w`), added `skipped_no_winner` for cancelled notices.
- **Job 3:** dossier downloader (PDF validate by magic-bytes, sha256 dedup,
  PyMuPDF text) + `python -m app.ingestion` CLI. **Gap:** SQLite couldn't run the
  `ON CONFLICT` upsert → moved DB tests onto a real `gtm_test` Postgres with a
  rollback-per-test fixture. **Latent bug fixed:** `server_default=func.false()`
  rendered invalid SQL `false()` → switched to SQLAlchemy `false()`.
- **Verified:** 57/57 tests; live dossier run `{downloaded:1, failed:4}` (4 portal
  landing pages correctly rejected by the magic-bytes check) + idempotency proven.

## ~2026-06-08 → 15 — PRs #5/#7/#9 + PR #8 integration fixes (first gap-driven review cycle)
- **Merged:** Phase-6 agent layer (PR #5: `controller`/`tools`/`reflector` +
  `agent_runs`), MVP backend APIs + Vue dashboard (PR #7), `easy_demo` GTM
  lead-scoring rebuild (PR #9).
- **Gap-driven reviews** wrote per-branch review docs that found concrete defects;
  **PR #8 fixed them:** the `/emails` endpoint referenced non-existent `Document`
  columns (only caught because tests were mock-based) → fixed + added real-DB
  regression tests (`test_api_real_db.py`); the agent's `query_db` substring guard
  blocked legit `created_at`/`comment` columns → replaced with a word-boundary
  regex; the SDK typed `block.input` as `object` flowing untyped into dispatch →
  normalised to `dict`. The agent's integration pass also added a `dry_run=True`
  default, graceful max-turns truncation, and the locked model id.
- **Key gap flagged (not yet fixable):** the agent's `find_matches`/`draft_email`
  tools pointed at Phase-3/4 stubs — sequencing problem, resolved later by R2/R4/R23.

## 2026-06-15 → 16 — Phase 3 matching pipeline + two-sided emails
- **Built:** the two-layer matcher — Layer 1 `build_company_profiles` (derive the
  supplier pool from award winners) + Layer 2 `MatchingPipeline.run` (disqualify →
  semantic + budget/location/qualification rules → weighted combine), plus
  supplier + buyer email endpoints. Migrations `0005` (`source_company_id`) and
  `0006` (buyer emails). This resolved the standing "matches/emails have no data
  producer" gap from the PR #7 review.
- **Live smoke (2026-06-16, `matching_pipeline_smoke_record.md`) found scoring
  gaps:** `qualification = 0` for every match (exact-CPV matching misses the
  shared `45` construction division), thin `company_profiles` text (semantic
  ≈0.24–0.31), and `budget = 0.5` everywhere (TED CNs omit budgets). These became
  G4/G6/G7 and were closed on 2026-06-21.

## 2026-06-16 — Awards ML-enrichment + rate-limit hardening
- **Trigger:** preparing a *full* back-fill to give the ML team real training data.
- **Gaps found + fixed:** (1) the full run tripped TED's nginx **429** → added
  per-host exponential backoff + bumped the inter-request delay; (2) `awards`
  stored who/how-much but not what/where/who-exactly → migration `0007` added 7
  ML columns (`notice_title`, `description`, `nuts_code`, `winner_identifier`, …),
  all verified populated live before coding; (3) name-only entity resolution
  false-merged firms → migration `0008` made it identifier-first (tax id) with a
  `clean_identifier()` guard against junk like "keine Angabe".
- **Verified:** 172 tests; live `--limit 5` write populated all new columns.

## 2026-06-17 — Full awards back-fill + ML dataset export + docs refresh
- **Ran** the 24-month back-fill: **~21,015 awards / ~15,129 companies**; exported
  `awards_training.csv` + `companies.csv` for the ML model (with documented data
  caveats: values not EUR-converted, `-1/0` sentinels, multilingual text).
- **Docs refresh:** brought README/architecture/Database docs current (they had
  drifted to "only Job 1 done").

---

## 2026-06-21 — Integration session: PR #10 + #11 merge analysis → systematic gap closure

This session is the core incremental-improvement arc: two teammate branches were
merged to `main`, analysed for gaps, and the gaps were closed one at a time, each
verified by tests and (for matching) a live smoke.

### Step 0 — Merge analysis + gap consolidation
- **Trigger:** PR #10 (`feat/pipeline-integration-ML-backend-frontend`) and PR #11
  (`feat/lr-matching-pipeline-v5`) merged to `main`.
- **Found:** PR #11 shipped a *much better* matching model (v5: trained Logistic
  Regression, 10 features, multilingual, honest Hit@3 ≈ 55%) but as a **standalone
  root-level script** (`exports_ml_pipeline.py`) reading CSVs — touching none of
  the app. Two matchers now coexisted: the live 4-feature fixed-weight one and the
  good-but-disconnected v5 one.
- **Done:** consolidated all per-branch reviews into a single
  `docs/integration_gap_tracker.md` (gaps G1–G26, prioritized), deleting the
  scattered review files. This became the backlog driving every step below.

### Steps 1–3 — Quick scoring wins (G17, G4, G5)
- **G17:** `rapidfuzz` was imported by v5 but declared in no requirements file →
  added to `requirements-ml.txt`.
- **G4:** replaced exact-CPV `qualification_score` with **hierarchical CPV-prefix
  partial credit** (8-digit=1.0 … shared `45` division=0.3) — the fix for the
  2026-06-16 `qualification=0` finding.
- **G5:** switched the embedder from English `all-MiniLM-L6-v2` to multilingual
  `paraphrase-multilingual-MiniLM-L12-v2` (same 384-d) to match the multilingual
  TED corpus.
- **Verified (live smoke):** re-embedded the full 15,129-company pool; on a Czech
  road tender the top matches became genuine Czech road builders (EUROVIA,
  STRABAG, SWIETELSKY), `qualification` went 0 → 0.2–0.9, semantic spread widened.
  Surfaced **G26** (re-matching crashed on the emails FK) for Step 4.

### Step 4 — Port the v5 model into the app (G1, G2, G3, G18, G26)
- **The keystone:** unified the two matchers. New `app/matching/features.py`
  (10 v5 features from DB), `lr_weights.py` loads the trained coef+intercept+scaler
  from `exports/model_params.json` (added a full-params export to v5), pipeline now
  runs **LR mode** (v5-style hard filter 15,129→≤200 → 10 features → `predict_proba`)
  with a fixed-weight fallback. Migration `0009` added the 9 feature columns.
  **G26 fixed** (delete dependent emails before the idempotent re-match).
- **Verified (live smoke):** LR mode live; hard filter narrowed 15,129→200; sensible
  rankings with per-feature LR explanations; the G26 fix confirmed by re-matching a
  tender that already had an email. 201/201 tests.

### Step 5 — Feedback → LR retraining loop (G8)
- **Built:** `FeedbackRetrainer` fits an LR on `(feedback.features, rating)` pairs
  and writes `model_params_feedback.json`, which the serving path prefers over the
  v5 base (revert by deleting the file). Migration `0010` adds `feedback.features`
  (a feature snapshot taken at submit time) and makes `feedback.match_id` nullable
  with `ON DELETE SET NULL` — so re-matching can't FK-crash or destroy training
  data (same bug class as G26, fixed properly). `POST /feedback/retrain` endpoint.
- **Verified:** 208/208 tests (incl. a real-sklearn retrain that learns the signal).

### G6 + G7 — Scoring-quality ceilings (semantic text + budgets)
- **G6:** `build_capability_text` now concatenates each company's award
  `notice_title` + `description` (v5-aligned) instead of a thin name+CPV blurb.
- **G7:** new `app/matching/money.to_eur` (FX table) converts award values + the
  tender budget to EUR and drops `-1/0` sentinels.
- **Verified (live smoke):** semantic cosines for relevant matches jumped from
  ~0.24–0.43 to **0.67–0.82**; P(win) rose from ~0.27 to **~0.79**; the
  €1.353 B-in-CZK artifact normalised to **€54 M**. Both changes also *reduced
  train/serve skew* by aligning the app to the model v5 already trained. 216 tests.

### G10 — Real Claude email drafter + unified drafting
- **Built:** one `EmailDrafter` path — Claude (`claude-sonnet-4-6`, evidence-
  constrained) with a deterministic template fallback on missing key / error /
  failed `EmailValidator`. `EvidenceExtractor` centralises the evidence dict; the
  supplier endpoint, buyer digest, and the **agent `draft_email` tool** (previously
  a dead-end stub) all route through it.
- **Verified:** 227/227 tests (Claude path via injected fake client; suite forced
  offline). **Live-verified:** with a valid key, Claude produced an evidence-
  grounded email for a German tender — auto-matching the language and citing only
  real facts (TED id, CPV codes, deadline). A bad-key run (a missing `sk-ant-`
  prefix) confirmed the graceful fallback in production.

### Net effect of 2026-06-21
Resolved **G1–G5, G8, G10, G17, G18, G26** (see tracker R12–R23). The matcher is
now unified and serves the trained v5 model behind the existing API/agent/
frontend; the feedback loop is live; emails are Claude-written. Remaining backlog:
G9/G13 (scheduler + reflection wiring), G11/G12 (understanding + cert gate),
G15/G16 (frontend), G19/G20 (hygiene).

## 2026-06-22 — CI hardening: ML-dependency isolation in the test suite
- **Trigger:** the GitHub Actions `backend-test` job failed on `main` —
  `test_retrain_writes_params_and_learns` raised `ModuleNotFoundError: No module
  named 'sklearn'` (226 passed, 1 failed).
- **Diagnosis (not a code bug):** by design the heavy ML deps live in
  `requirements-ml.txt` (torch / sentence-transformers / scikit-learn / joblib),
  and CI installs only the lean `requirements-dev.txt` so the suite stays fast and
  torch-free. Every matching/feedback test runs ML-dep-free by injecting fakes or
  returning before the lazy ML import — *except* the one Step-5 test that actually
  fits a real `sklearn` LogisticRegression to prove the feedback signal is learned.
- **Fix:** guarded that single test with `pytest.importorskip("sklearn")` — it runs
  locally (ML deps installed) and skips in CI. Mirrors how the suite already
  handles `torch`. CI is now green (`226 passed, 1 skipped`); local is `227 passed`.
- **Why it matters (report angle):** a clean payoff of the "ML-deps split + lazy
  import" decision — the app boots, CI runs, and the normal test run never pull the
  hundreds-of-MB ML stack; only the code paths that genuinely need it (real
  matching runs, model fits) load it, and the one test that fits a real model is
  `importorskip`-guarded rather than forcing ML deps into CI.

## 2026-06-23 — Pipeline completeness: Understanding layer + certification gate (G11/G12/G14)
- **Trigger:** the "Pipeline completeness" band of the gap tracker — the last
  structural stubs in the flow. G11 (no `FieldExtractor`) was blocking G12 (the
  disqualifier's cert gate, which had always been fed empty lists).
- **G11 — Understanding layer built.** `FieldExtractor.extract_tender` calls Claude
  (evidence-constrained JSON, lazy + injectable client, mirroring the G10 email
  drafter) to turn a tender's title + description + dossier text into a structured
  `TenderProfile` — summary, **required certifications**, required capabilities,
  keywords, language. Crucially the model only *enriches*: the trustworthy TED
  columns (CPV/title/budget/country/deadline) are passed in as the authoritative
  base and are the entire profile when no key is configured (deterministic
  fallback). `ExtractionValidator` repairs CPV format, drops `-1/0`/implausible
  budgets, flags past deadlines, dedupes list fields. `understanding.service`
  orchestrates and persists the result to the new `tenders.tender_profile` JSONB
  (migration `0013`) with a `_meta` provenance block. Surfaced as
  `POST /tenders/{id}/extract` and an `extract_tender_profile` agent tool. It is an
  **explicit opt-in step**, never run inside `MatchingPipeline.run`, so matching
  stays cheap and deterministic (≤1 LLM call per tender, only when asked).
- **G12 — cert gate wired, conservatively.** The pipeline now feeds the extracted
  `required_certifications` and each company's `company_profiles.certifications`
  into `Disqualifier.check`. The key design call: a hard gate must fire on evidence
  of *absence*, not *absence of evidence*. So the gate disqualifies only when a
  company's cert set is **known** (non-empty / explicitly flagged) and a required
  cert is missing — never when we simply have no cert data. Without this, a tender
  listing one required certification would disqualify the entire 15k-company pool
  (none of which carry cert data from TED awards). Result: the gate is fully wired
  and fires correctly in tests where a company has a known cert set, but is inert
  in production until a company-cert data source exists — the same "wired but
  data-limited" shape as G9's retrain.
- **G14 — fixed pool documented.** The supplier pool is exactly past TED award
  winners; company-side attributes award data lacks (chiefly certifications) are
  absent, which is *why* the G12 gate is production-inert. Recorded as an accepted
  V1 constraint in the tracker, `profile_builder`, and architecture docs; the lift
  path is a Phase-5 enriched "demand side" profile source.
- **Verified:** 246 → **266 tests** (+20: extractor fallback + Claude-via-fake-client,
  validator repairs, DB-backed service/endpoint persistence, conservative
  disqualifier semantics, pipeline cert gate with known/unknown/absent companies).
  Ruff-clean on all new code; single Alembic head `0013`; offline-safe in CI via the
  new `_offline_extractor` autouse fixture. **Migration `0013` applied** to the dev
  DB, then **live-verified**: Claude extracted a grounded structured profile from a
  real German landscaping tender (correct CPV `45112720`, German→English summary, a
  faithful 18-item capability list, real keywords) and correctly returned
  `required_certifications: []` because the notice states none — no hallucinated
  cert (parallels the G10 live email verify). See `docs/matching_pipeline_smoke_record.md`.

## 2026-06-23 — Frontend: awards/companies/agent UI + persisted weight re-rank (G15/G16)
- **Trigger:** the Frontend band of the gap tracker — the APIs for awards,
  companies, and the agent existed but had no UI, and the match weight sliders only
  recomputed client-side (nothing persisted).
- **G15 — three new screens.** Added Pinia stores + views + routes + nav for
  **Awards** (`GET /awards`: winner/buyer/value/date, search + country filter),
  **Companies** (`GET /companies`: canonical name + award-count/total-value
  rollups), and **Agent** (`POST /agent/run` -> planned steps + output;
  `POST /agent/reflect` -> metrics/actions/narrative). Each reuses the established
  live-API-or-sample-fallback pattern (modest sample arrays added to
  `sampleData.ts`) so every screen renders even with the backend down, and shows a
  Live/Sample source badge.
- **G16 — sliders that stick.** Extended `POST /matches/run/{id}` with an optional
  `weights` body; when supplied, the pipeline runs in legacy weighted mode and
  persists the operator's weights to `matches.weights`. `MatchesView` got an
  "Apply weights & re-rank (save)" action so the override is a durable server-side
  re-rank, not throwaway client state (the live client-side preview stays for
  instant feedback). The default body-less call still serves the trained LR.
  Honest framing: weighted mode is an operator *review* lever that intentionally
  overrides the calibrated model ranking — the signal that actually feeds G8
  retraining is still the thumbs-up/down feedback on the resulting matches.
- **Verified:** backend 266 -> **268 tests** (+2: weighted mode + zero-weight 422),
  ruff-clean; frontend `npm run lint` + `npm run build` (vue-tsc) clean; live API
  smoke returned 21,015 awards / 15,129 companies / 246 matches from the dev DB
  (Windows console needed UTF-8 stdout for Czech/Slovenian company names — the
  recurring cp1252 gotcha, not an API issue).

## 2026-06-23 — G17b honesty pass + a G16 follow-up bug fix (from a review sweep)
- **Trigger:** close G17b (the last frontend nit) and a requested thorough
  codebase review.
- **G17b — recipient + threshold honesty.** The supplier email recipient stopped
  fabricating an authoritative `sales@<domain>`: it now derives an explicitly
  *unverified* `info@<domain>` candidate from the company website (or "No verified
  contact on file" when there's none), and the UI flags it + links the site to find
  the real contact. Buyer outreach still targets the real TED buyer org. The
  match-status "ready" cut-off moved 0.8 → 0.6 (`READY_SCORE`) to match the
  calibrated LR's win-probability range — the old 0.8 essentially never fired, so
  "ready" counts read 0 even for strong matches.
- **Bug found in review (caused by G16) — fixed.** The weighted re-rank path
  (`use_lr=False`) skipped the pipeline hard filter, so it scored the **entire ~15k
  pool and persisted a match row per company** per "Apply weights" click. The hard
  filter now runs in *both* scoring modes (it no-ops on the small pools tests use,
  falling back to the full slice), bounding candidates/persisted rows to ≤200. The
  run endpoint also now reports the *actual* scorer mode (`lr` only when the model
  params are loaded, else `weighted`) instead of assuming `lr`.
- **Verified:** backend **268 tests** still green (the hard-filter change is
  test-safe — verified each pipeline test's tiny pool falls through the filter),
  ruff-clean; frontend lint + build clean.
- **Other review findings — now fixed (low priority cleanup):** AppShell header
  chips + "Pipeline" steps are now reactive to the stores (live tenders/ready-
  matches/drafts counts + a Live/Sample data badge) instead of hardcoded constants;
  the agent `find_matches` tool now runs on the agent loop's DB session (was opening
  its own); stale comments corrected (`tools.py` no longer claims the pipeline is a
  stub raising `NotImplementedError`; `feedback.py` docstring now describes the
  shipped G8 retrain instead of "Phase 5"); the generic `embeddings` Vector(768)
  table got an explicit **RESERVED / not-yet-wired** docstring (it's a deliberate
  cross-model reservation, not a forgotten stub — keep empty or drop via migration).
  All non-behavioural except the agent session change; 268 tests still green,
  frontend lint + build clean.

## 2026-06-30 — Agent rework: streaming + resumable + caged tools (G22)

- **Trigger (user, live demo).** The Agent screen was the demo-killer: given a
  goal naming a tender *in prose* (no id), the planner reached for `ingest_tenders`
  and `download_dossiers`, **"dry run" did not stop them** (it only skipped DB
  writes), so it ran a live 2,835-notice TED poll + a bulk portal sweep, drained
  Claude credits, and hung so hard that Ctrl+C wouldn't return (sync endpoint
  blocked in a threadpool that uvicorn's graceful shutdown waited on).
- **Root cause.** (a) `dry_run` gated writes, not network — `poll_contract_notices`
  ran `search_all_pages` regardless, and `dossier_downloader._process_one` did
  `client.get(url)` before any dry-run check; (b) no path to resolve a prose tender
  name to an id, so the model defaulted to "fetch from source"; (c) the off-scope
  `download_dossiers` bulk sweep was an advertised tool; (d) no per-run cost bound.
- **Fix (DB-first, caged, streaming, resumable).** Agent flow is now
  `find_tender` (local id/title lookup, no network) → `find_matches` (the
  deterministic MiniLM + trained-LR pipeline — the LLM never finds/invents a
  match) → grounded explanation. `download_dossiers` **removed** from the agent
  surface; `ingest_tenders`/`ingest_awards` **caged** (no network in dry-run;
  bounded + at-most-once live; `ingest_awards` refused unless a prior
  `find_matches` returned zero). The loop is a **streaming generator** emitting SSE
  (`status`/`step`/`awaiting_input`/`final`/`error`) so the UI shows live progress
  (the frozen-spinner/hang can't recur). Conversation persists to **`agent_sessions`
  (migration `0014`)**, so an `ask_user` pause (tender disambiguation) resumes via
  `POST /agent/run/{id}/continue` with the user's pick — true multi-turn, survives
  restart. Frontend reads the SSE stream → live activity log + disambiguation
  picker.
- **Bug found in the live smoke + fixed.** The model issued a `query_db` with a
  *guessed* schema (`companies` vs `company_profiles`, non-existent columns); the
  failed SELECT poisoned the shared run transaction → the next state-persist commit
  raised `InFailedSqlTransaction` and killed the run. **Fix:** run `query_db` inside
  a SAVEPOINT (`begin_nested`) so a bad query rolls back only itself; and have
  `find_matches` return the **structured top-N + sub-scores** so the model explains
  from real pipeline output instead of guessing SQL. Regression-tested.
- **Verified.** Backend 268 → **283 tests** (+15 offline guardrail tests: no-network
  dry-run, ingest ≤1×, awards gate both ways, ask_user pause/resume, max-turns
  truncation, bad-query no-poison). Ruff-clean; single Alembic head `0014`; frontend
  lint + build clean. **Live smoke (dry-run, real Claude):** partial name "Neubau
  school" → 4 local `find_tender` lookups → `ask_user` pause; resume with a picked
  id correctly mapped reply→`tender_id`, ran `extract_tender_profile` +
  `find_matches`, and explained the top-3 German HVAC firms **grounded only in the
  returned scores** (semantic 0.92–0.95, qual/location 1.0, budget 0.5). Direct-id
  path also clean. **Zero TED/portal calls** in either run.
- **Watch-item (documented).** On resume the picker sends the option's id as reply
  *text*; the model maps it back to the tender id from context. Confirmed working in
  both the disambiguation-resume and direct-id runs.

## 2026-07-01 — Agent follow-ups: public-id resolution + result actions (G28)

- **Trigger (user, continuing the demo).** Two things off the back of the agent
  rework: (1) the UI showed the internal db `id`, and the publicly-known
  `ted_notice_id` (which the detail panel highlights) couldn't be used as input;
  (2) the agent ended its run with a yes/no offer ("draft an email to the top
  match?") the UI had no way to answer — the run was already `final`, not
  `awaiting_input`.
- **Public-id pass.** `find_tender` now resolves by `ted_notice_id` (e.g.
  `420398-2026`) as well as internal id / title; its output + the ask_user picker
  lead with the TED id (internal `tender_id` kept only as the model's hidden handle).
  The **Tender-detail panel** gained a "TED notice ID" chip (styled like CPV codes).
  Decision: **don't expose internal db ids in the UI** — lean on the public TED id.
- **Honest dry-run label.** Post-rework the agent's `dry_run` only gates the caged
  ingest tools, so the checkbox was relabelled "Offline mode — only use
  already-ingested data" with a note that matching runs either way (it no longer
  over-promises "no writes").
- **Result actions (G28).** Two buttons on the agent result card:
  - **Save results** → `POST /api/v1/tenders/{id}/reports` persists the narrative +
    a **server-side snapshot** of the ranked matches to a new **`tender_reports`**
    table (migration `0015`, FK `tender_id`, `suppliers` JSONB). History kept; the
    snapshot is self-contained (survives a re-match — the `feedback.features` /
    G26 durability lesson).
  - **Draft email** with a 🥇/🥈/🥉 **selector** — the user picks *which* of the
    top-3 to write to (they may disagree with the model's top pick), routed to the
    existing `POST /emails/{match_id}/generate`; a "Email written with [company]"
    note links to the Emails screen. Top-3 sourced from `GET /matches?tender_id=`.
- **Read side (found while UI-testing — the write side was useless alone).** Two
  gaps surfaced: (1) the **Emails screen had no list endpoint**, so it always showed
  bundled sample data and agent-/per-match-generated emails were invisible — added
  **`GET /api/v1/emails/`** (list + `tender_id`/`recipient_type` filters) + an
  `EmailsView` fetch on mount. (2) **Saved analyses weren't viewable** — added a
  "Saved analyses" section on the Tender-detail panel reading
  `GET /tenders/{id}/reports` (narrative + supplier snapshot, collapsible).
- **Verify.** 283 → **288 tests** (+`find_tender` ted-id, +3 reports, +1 emails-list),
  ruff-clean, single head `0015`, frontend lint+build clean. **Live-smoked** against
  the dev DB (tender 2807): save → 200 + snapshot of the top-5 + list; **draft email
  for the non-top (🥉) pick** (Sauter Cumulus) produced a real grounded Claude email —
  confirming the user-choice requirement. The only hiccup was a `curl`-quoting 400
  (literal `\n` in a shell-single-quoted JSON body), not an API bug — a clean
  `urllib` POST returned 200. **Manual step:** `alembic upgrade head` (0015, applied).

---

# Future Decisions (design rationale)

> **Status (2026-06-17):** The **Agentic Flow Decision** below has been
> implemented along the recommended lines — Planner-executor on the native
> Anthropic SDK, ~6 tools, with a reflection loop, in 3 files
> (`app/agent/controller.py`, `tools.py`, `reflector.py`) and the `agent_runs`
> table. The matching pipeline it plans over is also live. The **PDF Scraping
> Decision** remains as recommended: deferred — the matcher runs on TED notice
> text + award history for V1. This section is kept as the design rationale.

## Agentic Flow Decision

Quick context check first: there's already a Phase 6 scaffold at [backend/app/agent/controller.py](../backend/app/agent/controller.py) ("Claude tool-use orchestrator that exposes ingestion/matching/generation as tools"), and CLAUDE.md §9 frames it as "AgentController exposes ingestion/matching/generation as Claude tools and drives multi-step workflows". So the agentic layer is already part of the plan — what hasn't been settled is *how agentic*, and where it adds real value vs. just being a thin wrapper over deterministic code.

Four ways to frame the agentic role, in increasing autonomy:

| Framing | What the agent does | Where it differs from a pipeline |
|---|---|---|
| **Tool-use shell** | User asks "find top 3 matches for the Frankfurt clinic tender", Claude picks tools (`match_tender`, `get_evidence`, `draft_email`) and returns a narrated answer. | Conversational, but the pipeline still owns the logic. |
| **Anomaly handler** | Pipeline runs deterministically (APScheduler ticks → ingest → match → draft). When something unusual happens (parse error, ambiguous winner name, novel CPV, low-confidence match), the agent gets invoked to decide. | Most of the time it's not running. When it does, it has real authority. |
| **Reflection loop** | After each end-to-end run, agent reviews the outputs ("today's 3 matches", "last week's email feedback ratings") and proposes adjustments ("the LR weights are over-emphasising location score; consider retraining"). Plus it writes a daily/weekly narrative report. | Adds the "self-improvement" angle that university juries usually like. |
| **Planner-executor** | User states a high-level goal ("find construction-tech companies in DACH that could win this week's renewable-energy tenders"), agent plans the multi-step sequence (ingest → filter CPVs → match → rank → email-draft), executes, summarises. | Most "agentic"; also the most demo-friendly. |

Implementation choices:

- **Anthropic SDK + tool use** (native, already in `requirements.txt`) — by far the simplest. Define 6-8 tools as JSON schemas wrapping the existing functions; let Claude pick the sequence. No framework dependency. This is what the scaffold already anticipates.
- **MCP (Model Context Protocol)** — newer standard for exposing tools to Claude. Would let you reuse the same tool definitions from Claude Code or Claude Desktop while developing. Useful, but not essential.
- **LangGraph / CrewAI / AutoGen** — heavier multi-agent frameworks. Probably overkill for a single-orchestrator pipeline; adds dependencies and a learning tax without obvious payoff at this scale.
- **Anthropic computer-use** (beta) — could attack the portal-scraping problem we discussed earlier by literally driving a browser. Cool demo material but slow, expensive, and not gating for the core pipeline.

### Recommendation

**Claude recommendation for this project specifically** — go with **Planner-executor + Reflection loop** built on the **native Anthropic SDK**. Concretely:

- `AgentController.run(user_goal: str)` opens a Claude session with ~7 tools: `ingest_contracts`, `ingest_awards`, `download_dossiers`, `find_matches(tender_id, top_n)`, `get_evidence(match_id)`, `draft_email(match_id)`, `query_db(read_only_sql)`.
- Claude plans → executes → narrates. Output saved to a `runs` table (new) so the agent can reference "what I did yesterday".
- Once a day (or post-feedback), a separate "reflection" prompt summarises recent activity + flags drift in matching quality.
- Prompt caching on the tool definitions + system prompt — keeps cost low even with many calls per run.

That hits both academic boxes — visible multi-step autonomy AND a self-improvement angle — without dragging in framework complexity. The whole agent layer is probably 2-3 files: `controller.py` (the loop), `tools.py` (schemas + dispatch), `reflector.py` (the daily narrative job).

**What actually shipped** (vs. the plan above): the 3 files exist as predicted. The tool set landed as **6 tools** — `ingest_tenders`, `ingest_awards`, `download_dossiers`, `find_matches`, `draft_email`, `query_db` (no separate `get_evidence` tool yet; evidence is folded into drafting). Two safety guards were added during integration: write-capable tools default to **`dry_run=True`** (so a chat goal can't trigger a live TED poll / DB write), and `query_db` is gated to a single read-only `SELECT` with a whole-word write-verb blocklist. Runs persist to `agent_runs`; `Reflector.run_daily_summary()` reads recent runs + feedback.


## PDF Scraping Decision

The 4 portals we hit during testing are each a national procurement system with its own URL scheme, auth flow, and sometimes its own API. There's no single solution; the realistic options sit on a cost / generality spectrum:

| Approach | Idea | When it fits |
|---|---|---|
| **Per-portal adapters** | Hand-coded `EvergabeAdapter`, `TenderArenaAdapter` etc. — each knows that portal's URL structure, dossier endpoint, optional login flow. Use httpx + a bit of HTML parsing (lxml/selectolax). | A handful of high-volume portals. Most accurate, most maintenance. |
| **Headless browser (Playwright)** | Open the portal page in a real browser, wait for JS, click around, dump the dossier link. No LLM. | JS-heavy portals that won't render with plain httpx. Slow, brittle when sites redesign. |
| **Commercial scraping APIs** | Browserless / ScrapingBee / Bright Data / Apify / Zyte — they run the browser + rotate IPs + handle CAPTCHAs. You give them a URL, they give you HTML or extracted text. | When anti-bot defenses matter. Cost: ~$30-300/mo at low volume. Out of scope for a uni project. |
| **LLM-driven generic scraping** | [Firecrawl](https://firecrawl.dev/) (HTML → markdown) + Claude to extract "what's the dossier URL on this page?". Or [browser-use](https://github.com/browser-use/browser-use) (Playwright + LLM-driven autonomous nav). Or Anthropic computer-use (beta — Claude drives a real browser). | Long tail of unknown portals. Most general, slowest, most expensive per page. |
| **Public portal APIs** | Some national systems (`eis.gov.lv`, `tenderned.nl`, Spain's PLACSP) publish open APIs. `OpenTenders.EU` aggregates many. | Free + authoritative when available. Coverage is patchy. |

**My take for this project specifically:** worth not building this yet. The 5 tenders we have show the issue clearly — 4 of 5 `document_url`s are portal landing pages, 1 is TED's own PDF mirror. For the matching pipeline (Phase 3), you have the **full TED notice envelope** in `tenders.raw_json` already — title, buyer, CPVs, budget, multilingual descriptions. That's enough to demonstrate semantic matching + scoring. The portal dossiers would add detail (technical specs, required certifications) that improves match quality, but they're not gating for a working V1.

If/when you do build it, the lowest-risk first step is a small **adapter registry** (`PORTAL_ADAPTERS = {"evergabe.de": EvergabeAdapter(), ...}`) that we extend one portal at a time as needed, with a generic **Firecrawl + Claude** fallback for everything else. That way we never block on a hard portal and we keep LLM costs low for the long tail.

The agent frameworks (browser-use, computer-use) are interesting but I'd hold off — they're the most generic but also the slowest, most expensive, and least reliable. Better as a Phase 6+ exploration once the core pipeline ships.

