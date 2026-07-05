# Architecture — confirmed decisions

This document captures the architectural choices already made for the GTM
Agent. Each entry is short and decision-shaped; expand with rationale and
alternatives as the design evolves.

## Confirmed

### Backend language and framework — Python 3.11 + FastAPI
Python 3.11 (explicit, not the system 3.14). FastAPI for the HTTP layer
because Pydantic v2 integration is first-class and OpenAPI generation
gives the frontend a typed client for free.

### ORM and migrations — SQLAlchemy 2.x + Alembic
SQLAlchemy 2.x with the new typed `Mapped[]` API. Alembic uses the
*direct* connection string (port 5432); the app uses the *pooled* one
(6543). Some DDL operations are unreliable through poolers, hence the
split.

### Database — Postgres 16 with pgvector
Single Postgres node with `pgvector/pgvector:pg16`. Vector columns live
in the `embeddings`, `company_profiles`, and matching pipeline outputs.
We avoid Supabase client libraries — we talk to Postgres directly via
psycopg and the SQLAlchemy engine.

### Embeddings — sentence-transformers, CPU-only, lazy-loaded
The matcher uses **`paraphrase-multilingual-MiniLM-L12-v2`** (384-d, multilingual —
the TED corpus spans 24 languages) — the dimension of `company_profiles.embedding`.
The ensemble vision (adding `all-mpnet-base-v2` 768-d and `multilingual-e5-large`
1024-d, stored in the generic `embeddings` table) stands but is not wired yet. All
models load lazily on first use; no GPU.

The ML stack (`sentence-transformers`, `scikit-learn`, `joblib`) lives in a
**separate `requirements-ml.txt`**, not the core runtime. Reason: `torch` is
heavy, and `app.matching.embedder` lazy-imports `sentence_transformers` while
unit tests inject fake embedders — so CI, the API boot, and the normal test run
stay torch-free and fast. The ML deps are only needed when matching actually
runs (`POST /api/v1/matches/run/{id}` or `build_company_profiles`).

### Matching — two-layer pipeline (`app/matching/`)
- **Layer 1 — supplier-pool builder** (`profile_builder.build_company_profiles`):
  derives a `company_profiles` row from each award-winner `companies` row +
  that company's `awards` history (capability text = name + CPV codes + regions;
  deal-size range from past contract values; MiniLM embedding). Idempotent via
  `source_company_id` upsert key. No web scraping in the MVP — profiles are
  intentionally thin (a known scoring limitation).
- **Layer 2 — matcher** (`pipeline.MatchingPipeline.run(tender_id)`): a v5-style
  hard filter narrows the ~15k pool to ≤200, then **the default path scores each
  candidate with a trained logistic regression** over 10 features
  (`predict_proba` → calibrated win-probability, with per-feature contributions),
  loaded from `exports/model_params.json` (or the feedback-retrained
  `model_params_feedback.json` when present). The legacy fixed-weight combine
  (`semantic 0.40 / budget 0.20 / location 0.20 / qualification 0.20`) remains as a
  fallback and as the operator weight-override re-rank (G16). Replaces that tender's
  `matches` rows idempotently (deleting dependent emails first to avoid the FK
  violation — G26).
- Embedder and weights are **injectable** so the pipeline's unit tests run
  without MiniLM/torch. Live-smoked 2026-06-16 — see
  [matching_pipeline_smoke_record.md](matching_pipeline_smoke_record.md).

### Generation — two-sided, evidence-grounded email backend (`app/api/v1/emails.py`)
Two recipient types share the `emails` table (`recipient_type` column):
- **supplier** — per-match outreach to the matched company.
- **buyer** — per-tender digest to the tender issuer, anchored to its top match,
  recommending the ranked suppliers.

Both drafts are **Claude-written and evidence-grounded** (G10): `EvidenceExtractor`
assembles the verifiable fact list, `EmailDrafter` (`claude-sonnet-4-6`) writes under
an evidence constraint with a deterministic template fallback (missing key / SDK error
/ validation failure), and `EmailValidator` is a structural guardrail. The agent's
Draft-email action and the per-match / buyer endpoints all route through this one path.
Stored drafts are listable via `GET /api/v1/emails/` (added 2026-07-01 so the UI shows
real drafts, not bundled samples).

### LLM — Claude Sonnet 4.6 via Anthropic SDK
Model id: `claude-sonnet-4-6`. Used for:
- multi-step **agent orchestration** (`AgentController`, reworked — see Agent below)
- the **reflection loop** (`Reflector`, daily/post-feedback narrative; G9)
- **structured field extraction** (Understanding layer `FieldExtractor`, G11 — live,
  persists a `TenderProfile` to `tenders.tender_profile`)
- **evidence-grounded email drafting** (`EmailDrafter`, G10 — live)

Every LLM path is offline-safe: a deterministic fallback runs when no
`ANTHROPIC_API_KEY` is configured, and tests inject fake clients.

### Agent — native Anthropic tool-use, planner-executor + reflection (`app/agent/`)
Built on the native Anthropic SDK (no LangGraph/CrewAI — see [Notes.md](Notes.md)).
**Reworked 2026-06-30/07-01 (G22 + G28) into a DB-first, streaming, resumable loop**
after a live demo exposed that the old design hit live TED and ran a bulk dossier
sweep *during a "dry run"*, drained Claude credits, and hung unkillably.

**Flow (DB-first).** The agent resolves the tender locally, runs the deterministic
matcher, and narrates the result: `find_tender` (local lookup by internal id, public
`ted_notice_id`, or title — no network) → optional `extract_tender_profile` →
`find_matches` (the trained-LR pipeline; the LLM never finds or invents a supplier,
it only *picks the tool* and *explains the returned scores*) → grounded top-N
explanation. `ask_user` pauses for disambiguation (e.g. a partial tender name that
matched several tenders).

**Tools** (`tools.py: AGENT_TOOLS`): `find_tender`, `find_matches`,
`extract_tender_profile`, `draft_email`, `query_db`, `ask_user`, and the two **caged**
ingest fallbacks `ingest_tenders` / `ingest_awards`. `download_dossiers` was **removed**
from the agent surface (off-scope PDF scraping; it was the bulk sweep that hung).

**Streaming + resumable.** The loop is a generator emitting Server-Sent Events
(`status` / `step` / `awaiting_input` / `final` / `error`) so the UI shows live
progress. The conversation persists to **`agent_sessions`** (migration `0014`), so an
`ask_user` pause resumes via `POST /api/v1/agent/run/{id}/continue`. Endpoints:
`POST /api/v1/agent/run` and `…/{id}/continue`, both SSE. Each completed run is also
written to `agent_runs` for the reflection loop.

**Post-run actions (G28).** The result card offers **Save results** → persists the
narrative + a server-side snapshot of the ranked matches to **`tender_reports`**
(migration `0015`), and **Draft email** with a 🥇/🥈/🥉 selector routing the chosen
match to `POST /emails/{match_id}/generate`.

**Safety decisions (post-rework):**
- **Dry-run means NO network.** The caged `ingest_*` tools short-circuit before any
  HTTP in dry-run and report what they *would* do; a live ingest is bounded
  (capped days/months + row limit) and runs **at most once per run**, with
  `ingest_awards` additionally gated on a prior zero-result `find_matches`. (The old
  `dry_run` only skipped DB writes, not the live TED poll / portal sweep — the
  demo-killer.)
- **`query_db` is read-only AND savepoint-isolated** — a single leading-`SELECT`
  with a whole-word write-verb blocklist (`\binsert\b`, `\bcreate\b`, …; the `\b`
  boundaries spare legit columns like `created_at` — see
  [integration_gap_tracker.md](integration_gap_tracker.md) R6), run inside a
  `begin_nested()` SAVEPOINT so a bad query (the model guessing a wrong column)
  can't poison the shared run transaction.
- **Bounded loop** (max 20 turns → partial progress on overflow) keeps cost and
  latency capped.

### REST API + frontend integration
All seven v1 routers are implemented (tenders, awards, companies, matches,
emails, feedback, agent) — list/detail/search + the `matches/run` and
`emails/*/generate` actions. The Vue frontend's Tenders/Matches/Emails views are
wired to these via Pinia stores, with bundled sample data as a fallback when the
API is unreachable.

### ML training dataset export (`exports/`)
The full awards back-fill (~21k awards / ~15k companies over 24 months) is
exported to CSV (`awards_training.csv`, `companies.csv`) as training data for the
tender↔company lead-scoring model. The v5 LR training harness
(`exports_ml_pipeline.py`) consumes them and writes `exports/model_params.json`,
which the in-app matcher loads. Data-quality caveats — `contract_value_eur`
is **not** FX-converted (read it with `contract_currency`); `-1`/`0` are
"not disclosed" sentinels; titles/descriptions are multilingual — are documented
in [exports/README.md](../exports/README.md).

### Frontend — Vue 3 + Vite + Pinia + Tailwind
TypeScript throughout. `openapi-typescript` will generate the API client
from the FastAPI schema once the v1 routes are real.

### Scheduling — APScheduler in-process
Lightweight, no broker dependency. **Implemented (G13):** `IngestionScheduler`
(`app/ingestion/scheduler.py`) wraps a `BackgroundScheduler` (UTC) with four cron
jobs — contracts (daily), dossiers (daily), awards (weekly), reflect (daily) — wired
into the FastAPI `lifespan`. **Opt-in** via `scheduler_enabled` (default off → CI /
tests / a normal dev boot never poll TED). The `python -m app.ingestion` CLI still
serves one-shot runs.

### CI — GitHub Actions
Three jobs on every push / PR: backend pytest, frontend lint + build,
Alembic upgrade check against a real pgvector service container.

## Deferred / not in scope yet

> Several items previously listed here shipped in the 2026-06-21→07-01 sprints —
> see `docs/integration_gap_tracker.md` for the authoritative status. **Now done:**
> APScheduler Job 4 (G13), the Understanding layer (G11), LR retraining from feedback
> (G8), Claude-written emails (G10), the awards/companies/agent UI + persisted weights
> (G15/G16), the **agent rework** (DB-first, streaming, resumable, caged tools — G22),
> and the **agent result actions** (Save results → `tender_reports`, Draft-email
> selector — G28). New tables since this doc's older snapshots: `reflections` (`0011`),
> `agent_sessions` (`0014`), `tender_reports` (`0015`). Migration head **`0015`**.

- **Web-scraped / enriched `company_profiles` ("demand side")** — profiles are
  derived from **past TED award winners only** (`profile_builder`), so the supplier
  pool is fixed and company-side attributes that award data lacks — chiefly
  **certifications** — are absent. This is an **accepted V1 constraint (G14)**, and
  it is *why* the certification disqualifier gate (G12), though fully wired to the
  Understanding layer's extracted `required_certifications`, stays inert in
  production: there is no company-cert data to gate against. The lift path is a
  Phase-5 scraped/enriched profile source (which also activates G12). Per-portal
  dossier scraping is deferred (see [Notes.md](Notes.md)).
- **Frontend for awards / companies / agent + persisted weights (G15/G16)** — the
  highest-value remaining band; APIs exist, the UI does not.
- Authentication & multi-tenant separation — Phase 5.
- Playwright E2E — install only when needed.
- DeepL / translation — out of scope; multilingual handled by a multilingual
  embedder.
- Background queue (Celery, RQ) — not needed at current scale.
