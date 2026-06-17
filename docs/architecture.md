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
The matcher currently uses **`all-MiniLM-L6-v2`** (384-d) — the dimension of
`company_profiles.embedding`. The ensemble vision (adding `all-mpnet-base-v2`
768-d and `multilingual-e5-large` 1024-d, stored in the generic `embeddings`
table) stands but is not wired yet. All models load lazily on first use; no GPU.

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
- **Layer 2 — matcher** (`pipeline.MatchingPipeline.run(tender_id)`): embeds the
  tender once, hard-disqualifies, then scores each candidate on semantic
  (cosine) + budget + location + qualification sub-scores, combines them with
  default weights (`semantic 0.40 / budget 0.20 / location 0.20 / qualification
  0.20`), and replaces that tender's `matches` rows (idempotent recompute).
- Embedder and weights are **injectable** so the pipeline's unit tests run
  without MiniLM/torch. Live-smoked 2026-06-16 — see
  [matching_pipeline_smoke_record.md](matching_pipeline_smoke_record.md).

### Generation — two-sided, evidence-grounded email backend (`app/api/v1/emails.py`)
Two recipient types share the `emails` table (`recipient_type` column):
- **supplier** — per-match outreach to the matched company.
- **buyer** — per-tender digest to the tender issuer, anchored to its top match,
  recommending the ranked suppliers.

Both drafts are currently **deterministic** (assembled from the match evidence,
not yet Claude-written) so the flow is demonstrable without LLM cost/latency.
The `EmailDrafter`/`EvidenceExtractor`/`EmailValidator` modules under
`app/generation/` remain stubs; swapping the inline drafter for a Claude call is
the planned upgrade.

### LLM — Claude Sonnet 4.6 via Anthropic SDK
Model id: `claude-sonnet-4-6`. Used for:
- multi-step **agent orchestration** (`AgentController`, implemented)
- the **reflection loop** (`Reflector`, daily/post-feedback narrative)
- structured field extraction (understanding layer — still a stub)
- evidence-grounded email drafting (planned upgrade — endpoints draft inline today)

### Agent — native Anthropic tool-use, planner-executor + reflection (`app/agent/`)
Built on the native Anthropic SDK (no LangGraph/CrewAI — see
[Notes.md](Notes.md)). `AgentController.run(goal)` runs a tool-use loop (max 20
turns) over **6 tools**: `ingest_tenders`, `ingest_awards`, `download_dossiers`,
`find_matches`, `draft_email`, `query_db`. Each run is persisted to the
`agent_runs` table; `Reflector` summarises recent runs + feedback. Two safety
decisions:
- **`dry_run` defaults to `true`** on both `AgentController` and
  `POST /api/v1/agent/run` — write-capable tools (`ingest_*`,
  `download_dossiers`) validate inputs and report what *would* happen rather
  than hitting live TED / writing the DB, so a casual chat goal can't trigger a
  live poll. Pass `dry_run=false` to opt in.
- **`query_db` is read-only** — gated to a single leading-`SELECT` statement
  with a whole-word write-verb blocklist (`\binsert\b`, `\bcreate\b`, …). The
  `\b` boundaries are deliberate so legitimate columns like `created_at` /
  `updated_at` / `comment` aren't rejected (the original substring guard blocked
  them — see [branch_review_agent_controller.md](branch_review_agent_controller.md)).

### REST API + frontend integration
All seven v1 routers are implemented (tenders, awards, companies, matches,
emails, feedback, agent) — list/detail/search + the `matches/run` and
`emails/*/generate` actions. The Vue frontend's Tenders/Matches/Emails views are
wired to these via Pinia stores, with bundled sample data as a fallback when the
API is unreachable.

### ML training dataset export (`exports/`)
The full awards back-fill (~21k awards / ~15k companies over 24 months) is
exported to CSV (`awards_training.csv`, `companies.csv`) as training data for the
tender↔company lead-scoring model. The standalone scoring pipeline lives in
`backend/easy_demo/` (its own README). Data-quality caveats — `contract_value_eur`
is **not** FX-converted (read it with `contract_currency`); `-1`/`0` are
"not disclosed" sentinels; titles/descriptions are multilingual — are documented
in [exports/README.md](../exports/README.md).

### Frontend — Vue 3 + Vite + Pinia + Tailwind
TypeScript throughout. `openapi-typescript` will generate the API client
from the FastAPI schema once the v1 routes are real.

### Scheduling — APScheduler in-process
Lightweight, no broker dependency. Intended for a daily TED pull + weekly award
back-fill. **Still a stub** (`app/ingestion/scheduler.py`) — ingestion runs via
the `python -m app.ingestion` CLI for now; the scheduler just wraps that CLI when
wired.

### CI — GitHub Actions
Three jobs on every push / PR: backend pytest, frontend lint + build,
Alembic upgrade check against a real pgvector service container.

## Deferred / not in scope yet
- **APScheduler wiring (Job 4)** — CLI exists; the in-process loop does not.
- **Understanding layer** — Claude `FieldExtractor` (tool-use enforced schema)
  + post-extraction validator. Today the matcher reads tender columns + dossier
  text directly instead of a structured `TenderProfile`.
- **LR weight retraining** — `feedback` is captured and `matches.weights` snapshots
  the weights used, but the logistic-regression learner that retrains from
  feedback (`app/matching/lr_weights.py`) is not yet driving live weights.
- **Claude-written emails** — endpoints draft deterministically; swapping in the
  `EmailDrafter` Claude call is the planned upgrade.
- **Web-scraped `company_profiles`** — profiles are derived from award history
  only (thin). Per-portal dossier scraping is deferred (see [Notes.md](Notes.md)).
- Authentication & multi-tenant separation — Phase 5.
- Playwright E2E — install only when needed.
- DeepL / translation — out of scope; multilingual handled by a multilingual
  embedder.
- Background queue (Celery, RQ) — not needed at current scale.
