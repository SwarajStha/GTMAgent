# GTM Agent

B2B lead-generation pipeline for the EU construction-tech sector. Pulls public procurement notices from TED (Tenders Electronic Daily), enriches them with downloaded dossier text, matches them against a supplier pool using a hybrid score (semantic embeddings + rule sub-scores), drafts evidence-grounded outreach emails for **both sides** of the deal (supplier outreach + buyer recommendation digest), and captures thumbs-up/down feedback. A Claude tool-use agent orchestrates the whole flow on demand. University group project — TUM CITHN2014.

For the decision log see [docs/architecture.md](docs/architecture.md); for the schema see [docs/Database_Explanation.md](docs/Database_Explanation.md); for teammate onboarding see [Guide.md](Guide.md).

---

## Evaluating this project? Start here

Fastest path from a fresh clone to a **populated, running app**. Docker is the only
prerequisite — no host Python needed:

```sh
cp backend/.env.example backend/.env                    # optional: add ANTHROPIC_API_KEY
docker compose up -d db                                 # 1. Postgres + pgvector
docker compose run --rm backend alembic upgrade head    # 2. create the schema
./scripts/seed/load_seed.sh                             # 3. load ~2 MB of real demo data
docker compose up -d --build                            # 4. backend + frontend
```

On Windows PowerShell, step 3 is `powershell -File scripts\seed\load_seed.ps1`.

Then open **http://localhost:5173** — Tenders, Matches, Companies, Awards, Emails and
saved agent analyses are all populated with real (public) EU procurement data.

| What | Where |
|---|---|
| Frontend | http://localhost:5173 |
| Interactive API docs | http://localhost:8000/docs |
| Health probe | http://localhost:8000/health |
| Postgres | `localhost:5432` direct, or `localhost:6543` pooled alias — same DB; user/password/db all `gtm` |

**No API key is needed to look around.** The seeded emails and agent reports are
pre-generated and the matching pipeline is deterministic, so every screen renders
without one. Only *new* LLM output — running the agent, drafting a fresh email,
extracting a tender profile — needs `ANTHROPIC_API_KEY` in `backend/.env`.

Details on the seed (what's in it, how to regenerate): [scripts/seed/README.md](scripts/seed/README.md).
Working on the code instead? See [Development setup](#development-setup).

---

## Current status

| Phase | What | Status |
|---|---|---|
| 1 | Repo scaffold, schema, CI | **Done** |
| 2 — Job 1 | TED Contract Notice poller + upsert | **Done — live-verified** |
| 2 — Job 2 | Awards back-fill + entity resolution | **Done — full back-fill: ~21k awards / ~15k companies** |
| 2 — Job 3 | Dossier downloader (PDFs from notice URLs) + ingestion CLI | **Done — live-verified** |
| 2 — Job 4 | APScheduler in-process loop | **Done — 4 cron jobs, opt-in via `SCHEDULER_ENABLED`** |
| 2 — Understanding | Claude `FieldExtractor` + validator | **Done — persists structured `TenderProfile`** |
| 3 | Matching (profile builder, disqualifier, embedder, semantic, rules) | **Done — v5 logistic-regression pipeline, live-smoked** |
| 4 | Generation (two-sided email backend: supplier + buyer drafts) | **Done — Claude drafter (`claude-sonnet-4-6`) + deterministic fallback** |
| 5 | Feedback capture endpoint | **Done — incl. LR-weight retraining from feedback; auth still pending** |
| 6 | Agent (Claude tool-use orchestrator + reflection loop) | **Done — DB-first, streaming (SSE) + resumable, 8 tools** |
| — | REST API (tenders/awards/companies/matches/emails/feedback/agent) | **Done — all 7 routers implemented** |
| — | Frontend (7 views wired to the API) | **Done — with sample-data fallback** |
| — | ML training dataset export (`archive/data-exports/`) | **Done — trained the v5 matcher** |

The one remaining gap is **auth / multi-tenancy** (deferred to a later phase — the LLM/ops endpoints are currently unauthenticated). The supplier capability profiles are still thin in the MVP — see [archive/internal-logs/matching_pipeline_smoke_record.md](archive/internal-logs/matching_pipeline_smoke_record.md) for the known scoring limitations.

---

## Prerequisites

**To run and evaluate the project, Docker Desktop is the only requirement** — the
commands above run Postgres, the backend and the frontend in containers. Python and
Node matter only if you want to develop against it ([Development setup](#development-setup)).

| Tool | Minimum version | Needed for |
|---|---|---|
| **Docker Desktop** | 24.x | **Everything — the only tool required to run the app.** Postgres 16 + pgvector, backend, frontend. |
| **Git** | any recent | Cloning the repo. |
| **Python** | **3.11 exactly** (NOT 3.12+) | *Development only.* Pinned deps (pgvector, psycopg, sentence-transformers ecosystem) target 3.11. |
| **Node.js** | 20.x LTS | *Development only.* Frontend dev server + build. |

### How to check each one

Run these in PowerShell / Terminal — each should print a version, not an error.

```powershell
docker --version                  # Docker version 24.x or newer
docker compose version            # Compose v2.x (NOT docker-compose v1)
docker ps                         # Should list running containers (or empty list) — confirms daemon is up
py -3.11 --version                # Python 3.11.x  (Windows; use `python3.11 --version` on macOS/Linux)
node --version                    # v20.x
npm --version                     # 10.x
git --version                     # any
```

If `docker ps` errors with "Cannot connect to the Docker daemon" or similar, start Docker Desktop first.

If `py -3.11` errors on Windows, install Python 3.11 from python.org and re-open the shell. The Python *launcher* (`py`) lets you pick a specific version even if your system default is something else.

### Optional but recommended

| Tool | Why |
|---|---|
| **DBeaver** or **pgAdmin** | GUI for browsing the Postgres data — connection details under [Database access](#database-access). |
| **VS Code** with Python + Vue extensions | The repo's structure assumes a multi-folder workspace. |

### Windows-specific gotchas

- **Local Postgres conflict**: If you ever installed Postgres directly on Windows (e.g. `postgresql-x64-18`), the Windows service binds `0.0.0.0:5432` on boot and silently steals the port from Docker. The symptom is misleading "password authentication failed" errors. Fix: open an Admin PowerShell and run `Stop-Service postgresql-x64-18; Set-Service postgresql-x64-18 -StartupType Manual`.
- **SSL cert verification failures** (`CERTIFICATE_VERIFY_FAILED` when hitting `*.europa.eu` or PyPI): caused by AV/proxy SSL inspection. We use the `truststore` package which reads the Windows cert store directly; for pip, pass `--trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org`.

---

## Stack summary

- **Backend**: Python 3.11 / FastAPI 0.115 / Pydantic v2 / SQLAlchemy 2.x / Alembic / psycopg 3 / httpx / pgvector / PyMuPDF (dossier text)
- **Database**: Postgres 16 + pgvector (`pgvector/pgvector:pg16`)
- **Frontend**: Vue 3 / TypeScript / Vite 5 / Pinia / vue-router 4 / Tailwind 3
- **ML / embeddings** (separate `requirements-ml.txt`, see below): `sentence-transformers` (the matcher uses `paraphrase-multilingual-MiniLM-L12-v2`, 384-d, CPU-only) + `scikit-learn` / `joblib` (v5 logistic-regression ranker + feedback retraining). Kept out of the core requirements because `torch` is heavy and the unit tests inject fake embedders.
- **LLM**: Claude Sonnet 4.6 (`claude-sonnet-4-6`) via the Anthropic SDK — drives the agent orchestrator, email drafter, tender extraction, and reflection loop
- **Scheduler**: APScheduler in-process — 4 cron jobs (contract poll / dossier sweep / award back-fill / reflection), opt-in via `SCHEDULER_ENABLED` (default off)
- **CI**: GitHub Actions — pytest, frontend lint+build, Alembic migration smoke

### Why ML deps are split out

`requirements.txt` is the lean runtime (no `torch`). `requirements-ml.txt` adds `sentence-transformers`, `scikit-learn`, and `joblib`. Install it only when you want **real** semantic matching or to build the `company_profiles` embeddings:

```sh
pip install -r backend/requirements-ml.txt
# locally add the SSL workaround flags (see Prerequisites)
```

The matching pipeline lazy-imports `sentence_transformers`, so the API and the test suite stay torch-free and fast; the ML stack is only pulled when `POST /api/v1/matches/run/{tender_id}` (or `build_company_profiles`) actually executes.

---

## Repo layout

```
GTMAgent/
├── backend/
│   ├── app/
│   │   ├── api/v1/           FastAPI routers — tenders, awards, companies,
│   │   │                       matches, emails, feedback, agent (all implemented)
│   │   ├── core/             config.py (pydantic-settings), logging.py, rate_limit.py
│   │   ├── db/               models.py (13 tables), session.py, migrations/ (0001–0015)
│   │   ├── ingestion/        ted_client, awards_client, dossier_downloader,
│   │   │                       entity_resolution, base_client, schemas, __main__ (CLI),
│   │   │                       scheduler (APScheduler, opt-in)
│   │   ├── understanding/    extractor, schemas, validator, service (Claude FieldExtractor)
│   │   ├── matching/         profile_builder (Layer 1), pipeline (Layer 2), disqualifier,
│   │   │                       embedder, semantic, rules, features, lr_weights, money
│   │   ├── generation/       evidence, drafter (Claude), validator
│   │   └── agent/            controller (streaming, resumable), tools (8), reflector, progress
│   ├── scripts/              ted_smoke, awards_smoke, agent_smoke, test_anthropic_schema,
│   │                           create_readonly_role.sql — see backend/scripts/README.md
│   ├── tests/                pytest suite (276 tests across 34 files)
│   ├── alembic.ini           script_location = app/db/migrations
│   ├── requirements.txt      lean runtime deps (no torch)
│   ├── requirements-ml.txt   sentence-transformers + scikit-learn + joblib
│   ├── requirements-dev.txt  -r requirements.txt + pytest + ruff
│   ├── .env.example          copy to backend/.env and fill in
│   └── Dockerfile
├── frontend/
│   ├── src/                  7 Vue views (Home/Tenders/Matches/Emails/Awards/
│   │                           Companies/Agent), Pinia stores, router
│   ├── package.json          + vite.config.ts, tailwind.config.ts, eslint.config.js
│   └── Dockerfile
├── scripts/
│   ├── init-pgvector.sql     CREATE EXTENSION IF NOT EXISTS vector (runs on first DB init)
│   └── seed/                 demo seed — seed_demo.sql, .sh/.ps1 loaders, generator
│                               (see scripts/seed/README.md)
├── exports/                  model_params.json — the runtime LR matcher artifact (+ README)
├── docs/                     architecture, system_architecture, Database_Explanation,
│                               agentic_behavior_description, Specifications
├── Reports/                  graded deliverables as Markdown (Project Management, User
│                               Guide, UAT, GenAI Safety) + Screenshots/
├── archive/                  provenance only, not needed to run — data-exports/ (ML
│                               training data), planning/, internal-logs/, data-samples/
│                               (see archive/README.md)
├── exports_ml_pipeline.py    v5 matcher trainer — regenerates exports/model_params.json
├── run_pipeline.py           trainer entry point
├── README_ML_PIPELINE.md     how the matcher was trained + evaluated
├── docker-compose.yml        db + backend + frontend
├── .github/workflows/ci.yml  3 CI jobs (GitHub only — see the CI note below)
├── .gitignore                excludes secrets, *.docx/*.pptx, Pitch Video/, caches
├── Guide.md                  teammate onboarding guide
└── README.md                 (this file)
```

---

## Development setup

> Only want to *run* it? Use [Evaluating this project? Start here](#evaluating-this-project-start-here)
> above — Docker-only, no host toolchain. This section is for working on the code.

### 1. Local dev loop (host backend + frontend, hot reload)

Run the DB in Docker, run backend + frontend on the host with hot reload.

**Backend** (Python 3.11 venv inside `backend/`, NOT the system default):

```powershell
# Windows PowerShell — from repo root
docker compose up -d db
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
# If you hit SSL errors on PyPI, add:
#   --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org
cp .env.example .env       # then edit ANTHROPIC_API_KEY
alembic upgrade head       # applies migrations 0001 → 0015
pytest tests -v            # 276 tests (needs the gtm_test DB — see backend/scripts/README.md)
uvicorn app.main:app --reload
```

```sh
# macOS / Linux
docker compose up -d db
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
pytest tests -v
uvicorn app.main:app --reload
```

> The full test suite touches a real Postgres `gtm_test` database. One-time setup
> (create the DB + `vector` extension) is documented in
> [backend/scripts/README.md](backend/scripts/README.md#one-time-test-database-setup).

**Frontend**:

```sh
cd frontend
npm ci          # use ci, not install — respects the committed lockfile
npm run dev
```

### 2. Run the ingestion pipeline (CLI)

All three ingestion jobs are exposed through one CLI (`backend/app/ingestion/__main__.py`). From inside `backend/` with the venv active:

```powershell
python -m app.ingestion --mode both                      # contracts + awards + dossiers
python -m app.ingestion --mode contracts --days 7 --dry-run
python -m app.ingestion --mode awards --backfill-months 12 --limit 50
python -m app.ingestion --mode both --no-dossiers
```

Exit code is `0` when every job finished clean, `1` if any reported `errors > 0` or `failed > 0`. For the interactive, two-phase diagnostic scripts (raw API peek + dry-run/live), see [backend/scripts/README.md](backend/scripts/README.md):

```powershell
python backend\scripts\ted_smoke.py             # dry-run, prints raw API + parsed summary
python backend\scripts\ted_smoke.py --live      # writes tender rows
python backend\scripts\awards_smoke.py --live   # writes awards + resolves companies
python backend\scripts\agent_smoke.py           # exercises the Claude agent loop (dry-run default)
```

### 3. Run matching + generation

Once tenders, awards, and companies exist, build the supplier pool and rank it for a tender. This needs the ML deps (`requirements-ml.txt`):

```powershell
# 1. Layer 1 — derive company_profiles (capability text + MiniLM embedding) from award winners
#    (call build_company_profiles(session); see archive/internal-logs/matching_pipeline_smoke_record.md)
# 2. Layer 2 — rank the pool for a tender and persist `matches`:
curl -X POST http://localhost:8000/api/v1/matches/run/1
# 3. Draft outreach for one match (supplier-facing):
curl -X POST http://localhost:8000/api/v1/emails/<match_id>/generate
# 4. Draft a buyer-facing digest of a tender's top suppliers:
curl -X POST http://localhost:8000/api/v1/emails/buyer/1/generate
```

`archive/internal-logs/matching_pipeline_smoke_record.md` has a copy-paste reproduction script and the current scoring caveats.

---

## API surface (v1)

All routers are mounted under `/api/v1` and documented interactively at http://localhost:8000/docs.

| Endpoint | Method | What it does |
|---|---|---|
| `/health` | GET | Liveness probe (used by Docker/CI/frontend) |
| `/api/v1/tenders` · `/{id}` | GET | List/search tenders; detail includes raw TED payload |
| `/api/v1/tenders/{id}/extract` | POST | Run the Claude Understanding layer → persist a structured `TenderProfile` |
| `/api/v1/tenders/{id}/reports` | GET · POST | List / save agent analyses (narrative + supplier snapshot) for a tender |
| `/api/v1/awards` · `/{id}` | GET | List/search award notices joined to resolved winner |
| `/api/v1/companies` · `/{id}` | GET | Canonical award-winner companies + award-history rollups |
| `/api/v1/matches` · `/{id}` | GET | Ranked tender × company-profile matches with score breakdown |
| `/api/v1/matches/run/{tender_id}` | POST | Run the matching pipeline for a tender, persist `matches` (optional `weights` body) |
| `/api/v1/emails` | GET | List stored drafts (filter by `tender_id` / `recipient_type`) |
| `/api/v1/emails/{match_id}/generate` | POST | Supplier-facing outreach draft (evidence-grounded) |
| `/api/v1/emails/buyer/{tender_id}/generate` | POST | Buyer-facing digest of top supplier matches |
| `/api/v1/emails/{email_id}` | GET · DELETE | Fetch / delete a stored draft |
| `/api/v1/feedback` | POST | Thumbs-up/down on a match (+ optional email) |
| `/api/v1/feedback/retrain` | POST | Retrain the LR weights from accumulated feedback |
| `/api/v1/agent/run` | POST | Run the Claude tool-use agent on a free-text goal — streams SSE (`dry_run` defaults to true) |
| `/api/v1/agent/run/{session_id}/continue` | POST | Resume a paused agent run (answers an `ask_user` prompt) — streams SSE |
| `/api/v1/agent/reflect` | POST | Run one reflection cycle (metrics + optional LR retrain) |
| `/api/v1/agent/scheduler` | POST | Runtime start/stop/status of the in-process scheduler |

---

## Connection strings

Two env vars, two ports, one database:

| Var | Port / DB | Used by |
|---|---|---|
| `DATABASE_URL` | 6543 (pooled alias), `gtm` | FastAPI app at runtime |
| `DATABASE_URL_DIRECT` | 5432 (direct), `gtm` | Alembic migrations only |
| `DATABASE_URL_TEST` | 5432 (direct), `gtm_test` | pytest fixtures (create/drop/rollback freely) |

Inside the Docker compose network both runtime URLs collapse to `db:5432`; the 6543 port is a host-side alias only. The split exists because some DDL operations are unreliable through connection poolers. The test suite uses a **separate** `gtm_test` database so it never touches dev data — one-time setup in [backend/scripts/README.md](backend/scripts/README.md#one-time-test-database-setup).

---

## Database access

Once the DB is up, you can browse it via:

- **psql in the container** (no install required):
  ```powershell
  docker exec -it gtmagent-db-1 psql -U gtm -d gtm
  ```
- **DBeaver / pgAdmin**: connect to `localhost:5432`, db `gtm`, user `gtm`, password `gtm`.
- **One-shot queries**: see [backend/scripts/README.md](backend/scripts/README.md) for canned commands.

---

## CI

GitHub Actions runs three jobs on every push and PR to `main`:

1. **backend-test** — Python 3.11, install dev deps, spin up a Postgres service + create `gtm_test`, `pytest tests` (276 tests; the matching/agent tests inject fakes so the run stays torch-free)
2. **frontend-lint** — Node 20, `npm ci`, `npm run lint`, `npm run build`
3. **migration-check** — Spins up a real `pgvector/pgvector:pg16` service, runs `alembic upgrade head` (0001 → 0015)

> **Note:** these jobs run on the GitHub remote where the project was developed. The
> workflow file (`.github/workflows/ci.yml`) ships with the repo for reference, but a
> GitLab copy will **not** execute it — there is no `.gitlab-ci.yml`. To run the same
> checks locally: `pytest tests -v` in `backend/`, and `npm run lint && npm run build`
> in `frontend/`.

---

## Contributing / branching

- `main` is the integration branch.
- Work on feature branches: `feature/<short-name>` or `job-<n>-<name>`.
- Open a PR for review before merging into `main`.
- Migration changes warrant explicit mention in the PR — they're global to the dev DB.

---

## Documentation map

| Document | What it covers |
|---|---|
| [Guide.md](Guide.md) | Teammate onboarding — end-to-end walkthrough of the system + local setup |
| [docs/architecture.md](docs/architecture.md) | ADR-style decision log — why the system is shaped this way |
| [docs/system_architecture.md](docs/system_architecture.md) | Current architecture in swim-lane form (frontend / backend / DB / external) |
| [docs/Database_Explanation.md](docs/Database_Explanation.md) | Table-by-table schema reference |
| [docs/agentic_behavior_description.md](docs/agentic_behavior_description.md) | How the agent plans, calls tools, and stays grounded |
| [docs/Specifications.md](docs/Specifications.md) | Technical Q&A on the design and implementation |
| [README_ML_PIPELINE.md](README_ML_PIPELINE.md) | How the v5 matcher was trained and evaluated |
| [scripts/seed/README.md](scripts/seed/README.md) | The demo seed — contents, loading, regeneration |
| [backend/scripts/README.md](backend/scripts/README.md) | Smoke harnesses, test-DB setup, DB cheatsheet |
| [Reports/](Reports/) | Graded course deliverables (Project Management, User Guide, UAT, GenAI Safety) |
| [archive/README.md](archive/README.md) | Provenance material kept for reference, not needed to run |
