# GTM Agent

B2B lead-generation pipeline for the EU construction-tech sector. Pulls public procurement notices from TED (Tenders Electronic Daily), extracts structured tender profiles via Claude, matches them against curated company profiles using a hybrid score (semantic embeddings + rule sub-scores), and drafts evidence-grounded outreach emails. University group project — TUM CITHN2014.

For the decision log see [docs/architecture.md](docs/architecture.md).

---

## Current status

| Phase | What | Status |
|---|---|---|
| 1 | Repo scaffold, schema, CI | Done |
| 2 — Job 1 | TED Contract Notice poller + upsert | **Done — 5 real rows in DB, end-to-end live-verified** |
| 2 — Job 2 | Awards back-fill | Pending |
| 2 — Job 3 | Dossier downloader (PDFs from notice URLs) | Pending |
| 2 — Job 4 | APScheduler in-process loop | Pending |
| 3 | Matching (disqualifier, embedder, semantic, rules, LR weights) | Stubs only |
| 4 | Generation (evidence, drafter, validator) | Stubs only |
| 5 | Feedback loop + auth | Not started |
| 6 | Agent (Claude tool-use orchestrator) | Stubs only |

Latest commit: `829f480 feat(ingestion): TED v3 Contract Notice poller (Job 1)`

---

## Prerequisites

Before running anything, you need these installed and working:

| Tool | Minimum version | Why |
|---|---|---|
| **Docker Desktop** | 24.x | Runs Postgres 16 + pgvector in a container; the app talks to it on `localhost:5432`. |
| **Python** | **3.11 exactly** (NOT 3.12+) | Pinned dependencies (pgvector, psycopg, sentence-transformers ecosystem) target 3.11. |
| **Node.js** | 20.x LTS | Frontend dev server + build. |
| **Git** | any recent | Cloning + branching. |

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
| **DBeaver** or **pgAdmin** | GUI for browsing the Postgres data (especially `tenders.raw_json`). Connect to `localhost:5432`, db `gtm`, user `gtm`, password `gtm`. |
| **VS Code** with Python + Vue extensions | The repo's structure assumes a multi-folder workspace. |

### Windows-specific gotchas

- **Local Postgres conflict**: If you ever installed Postgres directly on Windows (e.g. `postgresql-x64-18`), the Windows service binds `0.0.0.0:5432` on boot and silently steals the port from Docker. The symptom is misleading "password authentication failed" errors. Fix: open an Admin PowerShell and run `Stop-Service postgresql-x64-18; Set-Service postgresql-x64-18 -StartupType Manual`.
- **SSL cert verification failures** (`CERTIFICATE_VERIFY_FAILED` when hitting `*.europa.eu` or PyPI): caused by AV/proxy SSL inspection. We use the `truststore` package which reads the Windows cert store directly; for pip, pass `--trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org`.

---

## Stack summary

- **Backend**: Python 3.11 / FastAPI 0.115 / Pydantic v2 / SQLAlchemy 2.x / Alembic / psycopg 3 / httpx / pgvector
- **Database**: Postgres 16 + pgvector (`pgvector/pgvector:pg16`)
- **Frontend**: Vue 3 / TypeScript / Vite 5 / Pinia / vue-router 4 / Tailwind 3
- **Embeddings (future)**: sentence-transformers ensemble — `all-MiniLM-L6-v2` (384-d), `all-mpnet-base-v2` (768-d), `multilingual-e5-large` (1024-d), CPU-only
- **LLM**: Claude Sonnet 4.6 (`claude-sonnet-4-6`) via the Anthropic SDK
- **Scheduler**: APScheduler in-process (no broker)
- **CI**: GitHub Actions — pytest, frontend lint+build, Alembic migration smoke

---

## Repo layout

```
GTMAgent/
├── backend/
│   ├── app/
│   │   ├── api/v1/           FastAPI routers (stubs)
│   │   ├── core/             config.py (pydantic-settings), logging.py
│   │   ├── db/               models.py, session.py, migrations/
│   │   ├── ingestion/        ted_client.py, base_client.py, schemas.py + Job 2/3/4 stubs
│   │   ├── understanding/    extractor, schemas, validator (stubs)
│   │   ├── matching/         disqualifier, embedder, semantic, rules, lr_weights, pipeline (stubs)
│   │   ├── generation/       evidence, drafter, validator (stubs)
│   │   └── agent/            controller (stub)
│   ├── scripts/              ted_smoke.py — see backend/scripts/README.md
│   ├── tests/                pytest suite (33 tests; 5 ingestion, 1 health, 27 stub imports)
│   ├── alembic.ini           script_location = app/db/migrations
│   ├── requirements.txt      runtime deps
│   ├── requirements-dev.txt  -r requirements.txt + pytest + ruff
│   ├── .env.example          template
│   └── Dockerfile
├── frontend/
│   └── src/                  Vue components, views, stores, router
├── scripts/
│   ├── init-pgvector.sql     CREATE EXTENSION IF NOT EXISTS vector (runs on first DB init)
│   └── test_ted_api.py       teammate's parallel TED v1 private-search exploration
├── docs/                     Architecture + planning notes
├── docker-compose.yml        db + backend + frontend
├── .github/workflows/ci.yml  3 CI jobs
└── README.md                 (this file)
```

---

## Quick start

### 1. Fastest path — everything in Docker

```sh
cp backend/.env.example backend/.env   # then edit, set ANTHROPIC_API_KEY
docker compose up --build
```

Once it's up:
- API health: http://localhost:8000/health
- Frontend: http://localhost:5173
- Postgres: `localhost:5432` (direct) or `localhost:6543` (pooled alias) — same DB, two ports

### 2. Local dev loop (recommended once you're iterating)

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
alembic upgrade head
pytest tests -v            # should show 33 passed
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

**Frontend**:

```sh
cd frontend
npm ci          # use ci, not install — respects the committed lockfile
npm run dev
```

### 3. TED ingestion smoke test

The TED poller has a dedicated diagnostic script. See [backend/scripts/README.md](backend/scripts/README.md) for full usage. Quick version:

```powershell
# from repo root, with venv active
python backend\scripts\ted_smoke.py             # dry-run, prints raw API + parsed summary
python backend\scripts\ted_smoke.py --live      # writes 5 rows to the tenders table
```

---

## Connection strings

Two env vars, two ports, one database:

| Var | Port | Used by |
|---|---|---|
| `DATABASE_URL` | 6543 (pooled alias) | FastAPI app at runtime |
| `DATABASE_URL_DIRECT` | 5432 (direct) | Alembic migrations only |

Inside the Docker compose network both collapse to `db:5432`; the 6543 port is a host-side alias only. The split exists because some DDL operations are unreliable through connection poolers.

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

1. **backend-test** — Python 3.11, install dev deps, `pytest tests`
2. **frontend-lint** — Node 20, `npm ci`, `npm run lint`, `npm run build`
3. **migration-check** — Spins up a real `pgvector/pgvector:pg16` service, runs `alembic upgrade head`

---

## Contributing / branching

- `main` is the integration branch.
- Work on feature branches: `feature/<short-name>` or `job-<n>-<name>`.
- Open a PR for review before merging into `main`.
- Migration changes warrant explicit mention in the PR — they're global to the dev DB.

---

## Help / issues

See [docs/architecture.md](docs/architecture.md) for high-level decisions and [backend/scripts/README.md](backend/scripts/README.md) for ingestion smoke-test usage.
