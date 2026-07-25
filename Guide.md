# GTMAgent — Teammate Onboarding Guide

Welcome! This guide explains what GTMAgent is, what we've built so far, and how to get the project running on your machine. Read top-to-bottom on day one, then keep it open while you set things up locally.

Where this guide is *not* enough, the canonical sources are:
- [README.md](README.md) — user-facing quickstart
- [docs/architecture.md](docs/architecture.md) — decision log
- [docs/system_architecture.md](docs/system_architecture.md) — current system architecture (swim-lane view)
- [docs/Database_Explanation.md](docs/Database_Explanation.md) — table-by-table reference
- [backend/scripts/README.md](backend/scripts/README.md) — smoke harnesses & DB cheatsheet

---

## 1. What is this project and how does it work?

**GTMAgent** is a B2B lead-generation pipeline for the EU construction-tech sector. It is the group project for TUM course **CITHN2014**.

### The end-to-end vision (what the finished product does)

```
   ┌────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────┐    ┌──────────┐
   │  EU TED    │ →  │  Ingestion   │ →  │ Understanding│ → │ Matching │ → │ Outreach │
   │  Tender    │    │  (poll +     │    │  (Claude     │   │ (hybrid  │   │ (Claude  │
   │  Notices   │    │   PDF DL)    │    │   extracts   │   │  score)  │   │  drafts  │
   │            │    │              │    │   structure) │   │          │   │  emails) │
   └────────────┘    └──────────────┘    └─────────────┘    └──────────┘    └──────────┘
                                                                                  │
                                                                                  ▼
                                                                          ┌───────────────┐
                                                                          │  Feedback     │
                                                                          │  (👍/👎       │
                                                                          │   retrains    │
                                                                          │   weights)    │
                                                                          └───────────────┘
```

Step by step:

1. **Ingestion** — Pull public procurement notices ("tenders") from the EU's TED (Tenders Electronic Daily) API. Also back-fill historic awards (who won past contracts) and download the PDF dossiers attached to each notice.
2. **Understanding** — Use Claude (Anthropic's LLM) with structured tool-use to extract a clean `TenderProfile` from each messy multilingual notice + PDF text.
3. **Matching** — Compare each tender against a curated pool of construction-tech vendor "company profiles" using a hybrid score: semantic-embedding cosine similarity + rule-based sub-scores (budget fit, geographic fit, qualifications) + logistic-regression-learned weights.
4. **Generation** — For the top-scoring (tender, company) pairs, draft an evidence-grounded outreach email via Claude. Every claim in the email has to cite a passage from the tender dossier.
5. **Feedback loop** — Capture thumbs-up / thumbs-down ratings on the generated emails. Periodically retrain the LR weights so the system gets smarter at picking matches over time.

### Where we are today

We've shipped **ingestion** (Jobs 1–3) plus the **matching pipeline**, a **two-sided email backend**, the full **REST API**, a **Claude tool-use agent**, and a **frontend** wired to the API. The big remaining gaps are the APScheduler loop (Job 4), the Claude understanding/`FieldExtractor` layer, LR-weight retraining from feedback, and auth — those are still stubs. The MVP's supplier profiles and email drafts are intentionally thin/deterministic; richer versions are future work.

---

## 2. How the parts interact

```
┌────────────────────────────────────────────────────────────────────┐
│                          USER (browser)                            │
└─────────────────────────────┬──────────────────────────────────────┘
                              │ HTTP
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│   FRONTEND   —   Vue 3 + Vite dev server   (localhost:5173)        │
│   - HomeView, TendersView, MatchesView, EmailsView                 │
│   - Pinia stores call /api/v1/* via Vite proxy                     │
└─────────────────────────────┬──────────────────────────────────────┘
                              │ /api/v1/* and /health
                              │ (Vite dev-server proxy → backend)
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│   BACKEND   —   FastAPI on Uvicorn   (localhost:8000)              │
│   - app/main.py             create_app() factory, /health          │
│   - app/api/v1/*.py         REST routers (LIVE — 7 routers)        │
│   - app/ingestion/*.py      TED clients + CLI (LIVE)               │
│   - app/understanding/*.py  Claude field extractor (STUB)          │
│   - app/matching/*.py       Two-layer scoring pipeline (LIVE)      │
│   - app/generation/*.py     Email drafter modules (STUB; endpoints │
│                               draft inline in api/v1/emails.py)     │
│   - app/agent/*.py          Claude tool-use orchestrator (LIVE)    │
└─────────┬──────────────────────────────────┬───────────────────────┘
          │ SQLAlchemy 2.x                   │ httpx / anthropic SDK
          ▼                                  ▼
┌──────────────────────────┐    ┌──────────────────────────────────┐
│   DATABASE               │    │   EXTERNAL APIs                  │
│   Postgres 16 + pgvector │    │   - api.ted.europa.eu  (LIVE)    │
│   in Docker              │    │   - api.anthropic.com  (LIVE —   │
│   (localhost:5432)       │    │       agent + reflection loop)   │
└──────────────────────────┘    └──────────────────────────────────┘
```

### The flows that exist today

1. **`GET /health`** — Frontend `HomeView.vue` fetches `/health` on page load (Vite proxies to backend:8000). Backend returns `{"status":"ok","service":"gtm-agent-backend"}`.

2. **TED ingestion CLI** — A teammate (or the future scheduler) runs `python -m app.ingestion --mode {contracts,awards,both}`. The ingestion module calls `api.ted.europa.eu` over HTTPS via `httpx`, parses the notices, and **upserts** rows into `tenders` / `awards` / `companies` via SQLAlchemy. Idempotent.

3. **Dossier downloader** — Same CLI (dossiers run by default; `--no-dossiers` to skip) walks every `tenders` row with a `document_url`, downloads the PDF, validates it's really a PDF (magic-bytes), extracts text with PyMuPDF, and writes a `documents` row plus the file to `backend/storage/dossiers/<notice_id>/`.

4. **Matching pipeline** — `POST /api/v1/matches/run/{tender_id}` (or `MatchingPipeline().run(...)`) embeds the tender, scores every `company_profiles` row on semantic + budget + location + qualification, and persists ranked `matches`. The pool itself is built by `build_company_profiles()` from award winners.

5. **Two-sided email generation** — `POST /api/v1/emails/{match_id}/generate` drafts supplier outreach; `POST /api/v1/emails/buyer/{tender_id}/generate` drafts a buyer-facing digest of a tender's top suppliers. Both are evidence-grounded (deterministic for now).

6. **Feedback** — `POST /api/v1/feedback` records thumbs-up/down on a match (+ optional email) into the `feedback` table.

7. **Claude agent** — `POST /api/v1/agent/run` runs a planner-executor tool loop over 6 tools (ingest/download/match/draft/query_db), persisting each run to `agent_runs`. Write-capable tools default to dry-run.

8. **Frontend views** — Tenders/Matches/Emails views call the v1 API via Pinia stores (with bundled sample data as a fallback). The Matches view can trigger matching, generate supplier/buyer emails, and submit feedback.

### The flows that don't exist yet (you will build them)

- **Scheduler** — `app/ingestion/scheduler.py` is still a stub. APScheduler will wire the ingestion CLI to a cron-like in-process loop (daily tenders, weekly awards).
- **Understanding layer** — no Claude `FieldExtractor` yet; the matcher reads tender columns + dossier text directly instead of a structured `TenderProfile`.
- **LR weight retraining** — feedback is captured but nothing retrains `matches.weights` from it yet.
- **Claude-written emails** — the email endpoints assemble drafts deterministically; swapping in a Claude call (via the `app/generation/` modules) is the planned upgrade.
- **Richer supplier profiles** — `company_profiles` capability text is thin (name + CPV + region); enrich from dossier text / scraping later.

---

## 3. Progress so far

### Phase status

| Phase | Component | Status |
|---|---|---|
| **1** | Repo scaffold, DB schema, CI | ✅ Done |
| **2 / Job 1** | TED Contract Notice poller + upsert | ✅ Done, live-verified |
| **2 / Job 2** | Awards back-fill + entity resolution | ✅ Done — full 24-month back-fill (~21k awards, ~15k companies) + ML export |
| **2 / Job 3** | Dossier downloader (PDFs) + CLI orchestrator | ✅ Done, live-verified |
| **2 / Job 4** | APScheduler in-process loop (daily/weekly) | ⬜ Stub — not wired |
| **2 (rest)** | Understanding — Claude field extractor + validator | ⬜ Stubs only |
| **3** | Matching — profile builder, disqualifier, embedder, semantic, rules | ✅ Done — multi-supplier pipeline, live-smoked |
| **4** | Generation — two-sided email backend (supplier + buyer) | ✅ Done (deterministic drafts); Claude-written + `app/generation/` modules pending |
| **5** | Feedback capture endpoint | ✅ Endpoint done; LR retraining + auth ⬜ pending |
| **6** | Agent — Claude tool-use orchestrator + reflection loop | ✅ Done — planner-executor over 6 tools |
| **—** | REST API (7 routers) + frontend integration | ✅ Done |

### How "done" was accomplished

- **Database**: We use Postgres 16 with the `pgvector` extension, run in Docker. The schema is managed by Alembic migrations — **eight so far** (`0001_initial_schema` → `0008_company_registration_id`). Applying them is a single command: `alembic upgrade head`. See [docs/Database_Explanation.md](docs/Database_Explanation.md) for the migration history.
- **TED ingestion**: A FastAPI-independent module under `backend/app/ingestion/`. The crown jewels are `ted_client.py` (Contract Notices), `awards_client.py` (Award Notices + entity resolution), and `dossier_downloader.py` (PDFs). All three are exposed via a single CLI: `python -m app.ingestion`.
- **Upsert pattern**: Every ingestion path uses Postgres's `INSERT ... ON CONFLICT (ted_notice_id) DO UPDATE ... RETURNING (xmax = 0) AS inserted`. The `xmax = 0` trick distinguishes "newly inserted" from "updated existing row".
- **Entity resolution** (`entity_resolution.py`): **Identifier-first** — matches on `registration_id` (tax id from TED) when present, else on a normalised `resolution_key` (strip punctuation + legal suffixes like "GmbH"/"AG"/"Ltd"). Merges variant spellings sharing an id; splits distinct entities sharing a trading name. `clean_identifier()` rejects junk ids that would false-merge companies.
- **Matching** (`app/matching/`): two layers — `profile_builder.build_company_profiles()` derives the `company_profiles` supplier pool from award winners; `pipeline.MatchingPipeline.run()` ranks the pool for a tender. Embedder/weights are injectable so tests run torch-free.
- **Agent** (`app/agent/`): `controller.py` runs a Claude tool-use loop; `tools.py` defines the 6 tools + read-only `query_db` guard; `reflector.py` summarises recent runs + feedback.
- **Tests**: 349 across 34 files (stub imports, health, config, ingestion, matching, agent, understanding, and per-router API tests against a real `gtm_test` Postgres). Locally: 348 pass, 1 skips (a contract test that needs a feedback-tuned model on disk). CI skips a couple more that need the optional ML deps. CI runs them on every push.
- **ML export**: the full awards back-fill is exported to `exports/` (`awards_training.csv`, `companies.csv`), which feeds the v5 LR training harness (`exports_ml_pipeline.py`) that produces `exports/model_params.json` for the in-app matcher.
- **The empirically-hard TED API contract** — the TED v3 expert search rejects most "obvious" field names from the docs (`cpv-code` → use `classification-cpv`, `winner-name` → use `organisation-name-tenderer`, etc.). The current `TED_FIELDS` and `AWARD_FIELDS` lists were beaten into shape over multiple live iterations.

### What "live verified" means here

- `tenders` holds real rows from `api.ted.europa.eu` (DE/CZ/CH/FR/LV in the original smoke).
- `awards` / `companies` hold the full 24-month back-fill — **~21,015 awards / ~15,129 companies** (exported to `exports/`).
- `documents` rows distinguish successful PDF downloads from portal-locked / non-PDF failures.
- The matching pipeline has been live-smoked end-to-end on real data (profiles → ranked matches → buyer email) — see [archive/internal-logs/matching_pipeline_smoke_record.md](archive/internal-logs/matching_pipeline_smoke_record.md).

---

## 4. Tools and what they're for

| Tool | What it is | What we use it for |
|---|---|---|
| **Python 3.11** | Programming language (this exact version, not 3.12+) | Backend language. Pinned because some dependencies (pgvector, psycopg, sentence-transformers) target 3.11. |
| **FastAPI 0.115** | Modern Python web framework | The HTTP API. Auto-generates OpenAPI schema, integrates natively with Pydantic v2 for validation. |
| **Pydantic v2** | Data validation library | Validates incoming/outgoing JSON. Powers our `TenderProfile`, `CompanyProfile`, `AwardRow` schemas. |
| **SQLAlchemy 2.x** | Python ORM | Talks to Postgres. Uses the new typed `Mapped[]` API. All model classes live in `backend/app/db/models.py`. |
| **Alembic** | Database migration tool | Versions DB schema changes. Each migration is a Python file in `backend/app/db/migrations/versions/`. |
| **psycopg 3** | Postgres driver for Python | What SQLAlchemy uses under the hood to actually open Postgres connections. |
| **Postgres 16** | Relational database | The single source of truth. All tenders, awards, companies, etc. live here. |
| **pgvector** | Postgres extension for vector similarity | Stores the embedding vectors we'll use in Phase 3 for semantic matching. Adds a `Vector(N)` column type and cosine-distance operator. |
| **httpx** | Modern async-capable HTTP client | Outbound HTTP calls (TED API, PDF downloads). We banned `requests` in favour of this. |
| **truststore** | Bridges Python's `ssl` to the OS cert store | Fixes "CERTIFICATE_VERIFY_FAILED" errors on Windows machines with AV/proxy SSL inspection. |
| **PyMuPDF** | PDF parsing library | Extracts text from downloaded tender dossier PDFs. |
| **APScheduler** | In-process scheduler (cron-like) | Will run ingestion jobs on a schedule (daily TED poll, weekly awards back-fill). Not wired up yet. |
| **anthropic 0.39** | Anthropic Claude Python SDK | Our LLM client. We use model `claude-sonnet-4-6`. Tool-use is the primary integration pattern. |
| **pytest** | Python testing framework | Test runner. `pytest tests -v` from the `backend/` directory. |
| **ruff** | Python linter / formatter | Style enforcement; configured in `backend/pyproject.toml`. |
| **Vue 3** | Frontend framework | The UI. Composition API + `<script setup>` style. |
| **TypeScript** | Typed superset of JavaScript | Used throughout the frontend. |
| **Vite 5** | Frontend build tool + dev server | Hot-reload dev server on port 5173, proxies `/api` and `/health` to backend:8000. |
| **Pinia** | Vue state-management library | Holds shared state across views (tenders, matches, emails stores). |
| **vue-router 4** | Vue's official client-side router | Single-page app routing (4 routes today). |
| **Tailwind 3** | Utility-first CSS framework | All styling. No hand-written CSS apart from `@tailwind` directives. |
| **Docker** | Container runtime | Runs Postgres in an isolated container so you don't have to install Postgres on your laptop. Also defines a full-stack `docker-compose.yml` if you ever want to run everything containerised. |
| **Docker Compose** | Multi-container orchestration | Single YAML (`docker-compose.yml`) describes db + backend + frontend as one stack you can bring up with `docker compose up`. |
| **GitHub Actions** | CI/CD platform | Runs three jobs on every push/PR: backend pytest, frontend lint+build, Alembic migration smoke. Config: `.github/workflows/ci.yml`. |
| **TED v3 API** | Public EU procurement-data API | `api.ted.europa.eu` — where all our tender notices and award notices come from. No auth required. |
| **Anthropic API** | Claude LLM hosted service | Needs `ANTHROPIC_API_KEY` in `backend/.env`. Used for extraction, drafting, and the agent layer. |
| **sentence-transformers** | Embedding model library | Loads `all-MiniLM-L6-v2` (384-d) on CPU for semantic similarity in the matcher. In `requirements-ml.txt` (heavy `torch` dep), lazy-imported so the core API/tests stay torch-free. |
| **scikit-learn / joblib** | ML toolkit | The v5 LR matcher (trained offline by `exports_ml_pipeline.py`) + the feedback-driven LR weight learner. Also in `requirements-ml.txt`. |

---

## 5. Database sections (tables)

We have **11 tables** across **two sub-graphs**. `awards` are NOT children of `tenders` (TED publishes Contract Notices and Award Notices as separate publications), but the two halves are bridged at runtime by `company_profiles.source_company_id → companies.id` (the matcher's profile builder derives the supplier pool from award winners).

See [docs/Database_Explanation.md](docs/Database_Explanation.md) for the full reference (column types, sample rows, design rationale).

### Sub-graph A — Ingestion (populated)

| Table | Status | Purpose |
|---|---|---|
| `tenders` | **~10 rows** | Active EU procurement notices polled from TED. One row per Contract Notice. Upserted on `ted_notice_id`. |
| `awards` | **~21k rows** | Historical contract awards from TED (full 24-month back-fill). Who won what, for how much, when — plus ML-enrichment columns (title, description, procedure type, NUTS region, currency, winner tax id). |
| `companies` | **~15k rows** | Canonical legal entities resolved from award winners (identifier-first dedup). |
| `documents` | **populated** | PDF dossiers downloaded from `tenders.document_url`, with PyMuPDF-extracted text. Failure flags distinguish portal-locked vs non-PDF. |

### Sub-graph B — Matching, emails, feedback, agent (live)

| Table | Status | Purpose |
|---|---|---|
| `company_profiles` | **populated** | The matchable **supplier pool** (capability text + 384-d MiniLM embedding). Derived from award winners by the profile builder (`source_company_id` bridges back to `companies`). Distinct from `companies`. |
| `matches` | **populated** | Scoring results. One row per (tender, company_profile) pair. 4 sub-scores + final score + weights snapshot + explanation. |
| `emails` | **populated** | Outreach drafts — `recipient_type` is `supplier` or `buyer`. Subject, body, JSONB evidence. |
| `feedback` | live (endpoint) | Thumbs-up/thumbs-down ratings on matches/emails. Will drive LR weight retraining. |
| `embeddings` | empty | Generic vector store, separate from `company_profiles.embedding` so we can store 768-d mpnet or 1024-d multilingual-e5 vectors too. |
| `agent_runs` | live (agent) | One row per Claude agent execution (goal, tool steps, output). Powers the reflection loop. |
| `alembic_version` | meta | Single row tracking the applied migration. Today: `0008_company_registration_id`. |

### Why two "company-like" tables (`companies` vs `company_profiles`)?

Both exist on purpose, do not merge them.

- **`companies`** (Job 2): minimal legal-entity record. Created when we ingest an award and resolve the winner's name. Historical "who-wins-what" signal.
- **`company_profiles`** (Phase 3): the matchable supply side. In the MVP, **derived from award winners** by the profile builder (not yet scraped); holds capability text + embedding for semantic matching. UUID PK to fit the matching pipeline. Future work enriches these from dossier text / web scraping.

---

## 6. Remaining work (short)

Already done: ingestion (Jobs 1–3), the matching pipeline, the two-sided email backend, the full REST API, the Claude agent + reflection loop, frontend integration, and the ML dataset export. What's left:

- **Job 4 — APScheduler loop** — Wire `app/ingestion/scheduler.py` so the CLI runs automatically (daily tender poll, weekly awards back-fill).
- **Understanding layer** — `FieldExtractor` using Claude tool-use to turn raw `tenders.raw_json` + `documents.extracted_text` into a clean `TenderProfile`, plus a post-extraction validator. The matcher reads columns/dossier text directly today.
- **Phase 3 — scoring quality** — CPV-prefix matching for the qualification score, and richer `company_profiles` capability text (from dossiers / scraping) so semantic scores stop being thin. See [archive/internal-logs/matching_pipeline_smoke_record.md](archive/internal-logs/matching_pipeline_smoke_record.md).
- **Phase 4 — Claude-written emails** — fill in `app/generation/` (`EvidenceExtractor` / `EmailDrafter` with an evidence-only constraint / `EmailValidator`) and swap the inline deterministic drafter for a Claude call.
- **Phase 5 — Feedback → retraining + auth** — the LR weight retraining job that consumes `feedback`, plus basic multi-tenant auth.
- **Minor follow-ups** — multi-page TED pagination (`iterationNextToken`) untested at scale; favicon 404; extend `LEGAL_SUFFIXES` to non-Latin scripts (Bulgarian `ООД`, Polish `Sp. z o.o.`, etc.); add `_` to entity-resolution punctuation set.

---

## 7. Summary — what you should now understand

1. **GTMAgent is a B2B lead-gen pipeline** for the EU construction-tech sector — pull tenders from TED → enrich with dossier text → match against a supplier pool → draft two-sided outreach emails → learn from feedback, with a Claude agent orchestrating on demand.
2. **The stack is Python 3.11 + FastAPI + Postgres (with pgvector) + Vue 3 + Vite + Tailwind**, plus a separate `requirements-ml.txt` (sentence-transformers + scikit-learn). Docker runs the database; Alembic manages the schema.
3. **Ingestion is live and verified** (Jobs 1–3). The full 24-month awards back-fill produced ~21k awards / ~15k companies, exported to `exports/` for the ML model.
4. **Matching, the two-sided email backend, the REST API, and the Claude agent are all built and working.** Still stubs: the APScheduler loop, the Claude understanding/`FieldExtractor` layer, LR-weight retraining, and auth.
5. **The database has 11 tables in 2 sub-graphs**: ingestion (`tenders`, `awards`, `companies`, `documents`) and matching/emails/agent (`company_profiles`, `matches`, `emails`, `feedback`, `embeddings`, `agent_runs`) — bridged by `company_profiles.source_company_id`. Migration head is `0008`.
6. **The TED API contract is empirically discovered, not documented** — check the supported-fields list in a 400 response before touching `TED_FIELDS` / `AWARD_FIELDS`. Don't trust the official docs over the existing code.
7. **CI runs 3 jobs on every push**: backend pytest (349 tests, against a `gtm_test` Postgres), frontend lint+build, and an Alembic migration check against a fresh pgvector container.

---

## 8. Running the project on a Mac

These steps assume macOS 13+ (Apple Silicon or Intel). Adjust paths as needed.

### Step 1 — Install prerequisites

```bash
# Check what you already have:
docker --version             # need 24.x+
docker compose version       # need v2.x
python3.11 --version         # need exactly 3.11.x (not 3.12+)
node --version               # need v20.x LTS
npm --version                # need 10.x
git --version                # any
```

If any are missing:

```bash
# Docker Desktop for Mac → https://www.docker.com/products/docker-desktop/
# Then launch the Docker Desktop app once so the daemon starts.

# Homebrew → https://brew.sh/ (if you don't have it)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 3.11 (NOT the system default, NOT 3.12+):
brew install python@3.11

# Node 20 LTS:
brew install node@20
brew link --overwrite node@20

# Git (usually pre-installed via Xcode CLT):
xcode-select --install
```

### Step 2 — Clone the repo

```bash
cd ~/dev        # or wherever you keep code
git clone https://github.com/SwarajStha/GTMAgent.git
cd GTMAgent
```

### Step 3 — Configure environment variables

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` in your editor and fill in:

```
ANTHROPIC_API_KEY=sk-ant-...      # ask Swaraj for the team key, or use your own
```

Leave the `DATABASE_URL` lines as the defaults — they point at the Dockerised DB.

### Step 4 — Start the database

```bash
docker compose up -d db
```

Wait ~10 seconds for it to be healthy. Verify:

```bash
docker compose ps db
# Should show the db service as "healthy"
```

### Step 5 — Set up the backend (Python venv)

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
# optional — only for REAL semantic matching / building company_profile embeddings:
#   pip install -r requirements-ml.txt   (heavy: pulls torch)
alembic upgrade head            # applies migrations 0001 → 0008
pytest tests -v                 # 349 tests (needs the gtm_test DB — see Step 6)
```

### Step 6 — Create the test database (one-time)

The DB-touching tests use a separate `gtm_test` database. Create it once (these work
from anywhere inside the repo, including `backend/` — Compose finds
`docker-compose.yml` by searching up from your current directory):

```bash
docker compose exec db psql -U gtm -d gtm -c "CREATE DATABASE gtm_test;"
docker compose exec db psql -U gtm -d gtm_test -c "CREATE EXTENSION vector;"
```

Re-run `pytest tests -v` — you should see 348 passed, 1 skipped on Postgres.

### Step 7 — Start the backend dev server

From inside `backend/` with the venv active:

```bash
uvicorn app.main:app --reload
```

You should see uvicorn logs like:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

Confirm in a browser: open http://localhost:8000/health — should return `{"status":"ok","service":"gtm-agent-backend"}`.

### Step 8 — Start the frontend dev server

In a **new terminal** (leave uvicorn running):

```bash
cd ~/dev/GTMAgent/frontend
npm ci                          # uses the committed lockfile (do NOT use `npm install`)
npm run dev
```

You should see Vite logs like:
```
  VITE v5.x.x  ready in 400 ms
  ➜  Local:   http://localhost:5173/
```

### Step 9 — Open the app in a browser

Visit http://localhost:5173. You should see:

- The **AppShell** with a top nav: Home / Tenders / Matches / Emails.
- The **Home view** showing the placeholder banner plus "**Backend status: ok**" — that's the frontend calling `/health` via the Vite proxy.

The other three views (Tenders / Matches / Emails) are wired to the v1 API via Pinia stores, with bundled sample data as a fallback when the backend has no rows yet. The Matches view can trigger the matching pipeline, generate supplier/buyer emails, and submit feedback.

### Step 10 — Smoke-test the TED ingestion (optional but satisfying)

From inside `backend/` with the venv active:

```bash
# Dry-run — fetches from TED, parses, doesn't write to DB:
python scripts/ted_smoke.py

# Live — writes ~5 tender rows:
python scripts/ted_smoke.py --live

# Then peek at the data:
docker compose exec db psql -U gtm -d gtm -c "SELECT ted_notice_id, buyer_country, deadline FROM tenders;"
```

### What to expect on first run

- **First `docker compose up -d db`** pulls the `pgvector/pgvector:pg16` image (~400 MB). Takes 30–60 seconds depending on connection.
- **First `pip install -r requirements-dev.txt`** downloads and builds wheels for ~40 packages. Takes 2–5 minutes. PyMuPDF and pgvector may compile from source briefly.
- **First `npm ci`** downloads ~300 MB into `node_modules/`. Takes 1–2 minutes. You may see deprecation warnings — they're benign (a dev-server-only esbuild advisory that doesn't affect production builds).
- **First `alembic upgrade head`** runs the migrations in sequence and prints `INFO  [alembic.runtime.migration] Running upgrade ...` lines. Takes <2 seconds.
- **First `pytest tests -v`** — 349 tests, takes ~10–20 seconds. If any test fails on first run, the most likely cause is that you forgot Step 6 (create `gtm_test` database) — fix that and re-run.
- **Browser loads the Home view in ~300ms** with a clean "Backend status: ok" line. If that line says "Backend status: error" or never shows, your `uvicorn` isn't running or the Vite proxy can't reach it — check that uvicorn shows traffic in its log when you reload the page.

### Common Mac-specific gotchas

- **Port 5432 conflict** — If you have Postgres.app or `brew install postgresql` running, port 5432 will be taken and Docker silently loses. Symptom: "password authentication failed" errors that don't match the password you set. Fix: `brew services stop postgresql` (or quit Postgres.app), then re-run `docker compose up -d db`.
- **Python launcher** — On Mac there's no `py -3.11`; use `python3.11` directly. Once the venv is active (`source .venv/bin/activate`), plain `python` and `pip` resolve to the venv's 3.11.
- **Apple Silicon (M1/M2/M3)** — All our deps have ARM wheels. PyMuPDF, psycopg, and pgvector all build fine on Apple Silicon. No special flags needed.
- **`docker compose` vs `docker-compose`** — We use Compose v2 syntax (`docker compose`, with a space). If your `docker --version` is 20.x or older, upgrade Docker Desktop.

### When you're done for the day

This is the dev-loop teardown (DB in Docker, servers on the host). If you ran the
**full stack** in Docker instead, see the teardown note at the end of
[README.md → Evaluating this project](README.md#evaluating-this-project-start-here) —
that one also frees the backend/frontend ports (`8000`, `5173`).

```bash
# Stop the dev servers: Ctrl+C in each terminal (uvicorn + vite).
# Stop the DB container:
docker compose stop db          # preserves data
# OR
docker compose down             # stops and removes the container (DB data persists in the named volume `pgdata`)
# OR (nuclear — wipes the DB):
docker compose down -v          # also drops the volume; you'll need to re-run `alembic upgrade head` next time
```

---

## Where to ask questions

- **Architecture / why-is-it-shaped-this-way**: [docs/architecture.md](docs/architecture.md) and [docs/system_architecture.md](docs/system_architecture.md).
- **Database tables**: [docs/Database_Explanation.md](docs/Database_Explanation.md).
- **TED API quirks / field names**: the field lists + inline comments in [backend/app/ingestion/ted_client.py](backend/app/ingestion/ted_client.py) (contract notices) and [backend/app/ingestion/awards_client.py](backend/app/ingestion/awards_client.py) (award notices) — read these BEFORE editing any ingestion field list.
- **Smoke harnesses & DB cheatsheet**: [backend/scripts/README.md](backend/scripts/README.md).
- **Future-work design notes (agent layer, PDF scraping)**: [archive/internal-logs/Notes.md](archive/internal-logs/Notes.md).
- **Anything else**: ping Swaraj on the group chat.

Welcome aboard 🚧
