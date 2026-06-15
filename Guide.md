# GTMAgent — Teammate Onboarding Guide

Welcome! This guide explains what GTMAgent is, what we've built so far, and how to get the project running on your machine. Read top-to-bottom on day one, then keep it open while you set things up locally.

Where this guide is *not* enough, the canonical sources are:
- [README.md](README.md) — user-facing quickstart
- [CLAUDE.md](CLAUDE.md) — internal engineering scratchpad (the source of truth; gitignored on Swaraj's machine but kept up to date there)
- [docs/architecture.md](docs/architecture.md) — decision log
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

We've shipped the **ingestion** side end-to-end (Jobs 1, 2, 3). The understanding, matching, generation, and feedback layers exist as **stub files** — empty modules with the right names and import paths, ready to be filled in by you and the team.

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
│   - app/api/v1/*.py         REST routers (stubs)                   │
│   - app/ingestion/*.py      TED clients (LIVE)                     │
│   - app/understanding/*.py  Claude field extractor (STUB)          │
│   - app/matching/*.py       Scoring pipeline (STUB)                │
│   - app/generation/*.py     Email drafter (STUB)                   │
│   - app/agent/*.py          Multi-step orchestrator (STUB)         │
└─────────┬──────────────────────────────────┬───────────────────────┘
          │ SQLAlchemy 2.x                   │ httpx
          ▼                                  ▼
┌──────────────────────────┐    ┌──────────────────────────────────┐
│   DATABASE               │    │   EXTERNAL APIs                  │
│   Postgres 16 + pgvector │    │   - api.ted.europa.eu  (LIVE)    │
│   in Docker              │    │   - api.anthropic.com  (STUB)    │
│   (localhost:5432)       │    │                                  │
└──────────────────────────┘    └──────────────────────────────────┘
```

### The flows that exist today

1. **`GET /health`** — Frontend `HomeView.vue` fetches `/health` on page load (Vite proxies to backend:8000). Backend returns `{"status":"ok","service":"gtm-agent-backend"}`. This is the only end-to-end UI-to-backend flow currently wired up.

2. **TED ingestion CLI** — A teammate or the (future) scheduler runs `python -m app.ingestion --mode contracts` or `--mode awards`. The ingestion module calls `api.ted.europa.eu` over HTTPS via `httpx`, parses the notices, and **upserts** rows into the `tenders` / `awards` / `companies` tables via SQLAlchemy. Idempotent — you can run it twice without duplicates.

3. **Dossier downloader** — Same CLI (`--mode contracts` with dossiers enabled by default) walks every row in `tenders` that has a `document_url`, downloads the PDF via `httpx`, validates that it really is a PDF (magic-bytes check), extracts the text with PyMuPDF, and writes a row to `documents` plus the file to `backend/storage/dossiers/<notice_id>/`.

### The flows that don't exist yet (you will build them)

- **Matching pipeline trigger** — There's no endpoint or CLI to take a tender, run the scorer, and write `matches` rows yet.
- **Email generation** — No code yet that reads a high-score match and asks Claude to draft an email.
- **Feedback ingest** — `POST /api/v1/feedback` exists as a stub but doesn't do anything.
- **Scheduler** — `app/ingestion/scheduler.py` is empty. APScheduler will wire the ingestion CLI to a cron-like in-process loop.

---

## 3. Progress so far

### Phase status

| Phase | Component | Status |
|---|---|---|
| **1** | Repo scaffold, DB schema, CI | ✅ Done |
| **2 / Job 1** | TED Contract Notice poller + upsert | ✅ Done, live-verified (5 rows in DB) |
| **2 / Job 2** | Awards back-fill + entity resolution | ✅ Done, merged to main (5 awards, 5 companies) |
| **2 / Job 3** | Dossier downloader (PDFs) + CLI orchestrator | ✅ Code complete, live-verified (1 PDF on disk, 4 portal-locked) — PR open |
| **2 / Job 4** | APScheduler in-process loop (daily/weekly) | ⬜ Not started |
| **2 (rest)** | Understanding — Claude field extractor + validator | ⬜ Stubs only |
| **3** | Matching — disqualifier, embedder, semantic, rules, LR weights | ⬜ Stubs only |
| **4** | Generation — evidence extractor, drafter, validator | ⬜ Stubs only |
| **5** | Feedback loop + auth | ⬜ Not started |
| **6** | Agent — Claude tool-use orchestrator | ⬜ Stubs only |

### How "done" was accomplished

- **Database**: We use Postgres 16 with the `pgvector` extension, run in Docker. The schema is managed by Alembic migrations — three so far (`0001_initial_schema`, `0002_awards_companies`, `0003_add_documents`). Applying a migration is a single command: `alembic upgrade head`.
- **TED ingestion**: A FastAPI-independent module under `backend/app/ingestion/`. The crown jewels are `ted_client.py` (Contract Notices), `awards_client.py` (Award Notices + entity resolution), and `dossier_downloader.py` (PDFs). All three are exposed via a single CLI: `python -m app.ingestion`.
- **Upsert pattern**: Every ingestion path uses Postgres's `INSERT ... ON CONFLICT (ted_notice_id) DO UPDATE ... RETURNING (xmax = 0) AS inserted`. The `xmax = 0` trick is how we distinguish "newly inserted" from "updated existing row" — Postgres sets `xmax` to 0 on a fresh insert.
- **Entity resolution** (`entity_resolution.py`): Normalises winner names (strip punctuation, strip legal suffixes like "GmbH"/"AG"/"Ltd"), keyed on a `resolution_key`, so variant spellings of the same company collapse to one row in `companies`.
- **Tests**: 57/57 passing locally — 28 stub-import smoke tests, 1 health check, 5 TED contract tests, 10 awards tests, 14 dossier tests. CI (GitHub Actions) runs all of them on every push.
- **The empirically-hard TED API contract** — see [CLAUDE.md §14 and §15](CLAUDE.md) and the iteration logs there. The short version: the TED v3 expert search rejects most "obvious" field names from the docs (`cpv-code` → use `classification-cpv`, `winner-name` → use `organisation-name-tenderer`, etc.). The current `TED_FIELDS` and `AWARD_FIELDS` lists in the code were beaten into shape over multiple live iterations.

### What "live verified" means here

- `tenders` table has 5 real rows from `api.ted.europa.eu` (Germany, Czechia, Switzerland, France, Latvia).
- `awards` table has 5 real rows; `companies` has 5 resolved winners.
- `documents` table has 5 rows: 1 successful PDF download (the Swiss tender — TED's own PDF mirror) + 4 correctly-flagged failures (buyer-portal landing pages returning HTML instead of PDFs).

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
| **sentence-transformers** *(future)* | Embedding model library | Will load three local models (MiniLM-L6, mpnet-base, multilingual-e5) on CPU for semantic similarity scoring in Phase 3. |

---

## 5. Database sections (tables)

We have **10 tables** across **two disconnected sub-graphs** by design. There is no FK directly linking the two halves — `awards` are NOT children of `tenders` because TED publishes Contract Notices and Contract Award Notices as separate publications.

See [docs/Database_Explanation.md](docs/Database_Explanation.md) for the full reference (column types, sample rows, design rationale).

### Sub-graph A — Ingestion (populated today)

| Table | Status | Purpose |
|---|---|---|
| [`tenders`](docs/Database_Explanation.md#tenders--5-rows-populated-by-job-1) | **5 rows** | Active EU procurement notices polled from TED. One row per Contract Notice. Upserted on `ted_notice_id`. |
| [`awards`](docs/Database_Explanation.md#awards--5-rows-populated-by-job-2) | **5 rows** | Historical contract awards from TED. Who won what, for how much, when. |
| [`companies`](docs/Database_Explanation.md#companies--5-rows-populated-by-job-2-via-entity-resolution) | **5 rows** | Canonical legal entities resolved from award winners. Variant spellings ("Hochtief AG" / "Hochtief Aktiengesellschaft") collapse to one row. |
| [`documents`](docs/Database_Explanation.md#documents--phase-2-job-3-pending) | **5 rows** (1 PDF, 4 portal-locked) | PDF dossiers downloaded from `tenders.document_url`, with PyMuPDF-extracted text. |

### Sub-graph B — Matching, emails, feedback (empty until Phase 3+)

| Table | Status | Purpose |
|---|---|---|
| `company_profiles` | empty | The **vendors we want to pitch to**. Scraped capability profiles with 384-d MiniLM embeddings. Distinct from `companies` — different concern, different lifecycle. |
| `matches` | empty | Scoring results. One row per (tender, company_profile) pair the pipeline considered. 4 sub-scores + final score + LR weights snapshot + explanation. |
| `emails` | empty | LLM-generated outreach drafts. Subject, body, JSONB evidence (the passages from the dossier that grounded each claim). |
| `feedback` | empty | Thumbs-up/thumbs-down ratings on emails. Drives LR weight retraining. |
| `embeddings` | empty | Generic vector store, intentionally separate from `company_profiles.embedding` so we can store 768-d mpnet or 1024-d multilingual-e5 vectors too. |
| `alembic_version` | meta | Single row tracking which migration is currently applied. Today: `0003_add_documents`. |

### Why two "company-like" tables (`companies` vs `company_profiles`)?

Both exist on purpose, do not merge them.

- **`companies`** (Job 2, populated): minimal legal-entity record. Created when we ingest an award and resolve the winner's name. Used as historical "who-wins-what" signal.
- **`company_profiles`** (Phase 5, empty): the actual demand side of matching. Scraped from vendor websites, holds capabilities + certifications + embedding for semantic matching. UUID PK to fit the matching pipeline.

---

## 6. Remaining work (short)

- **Job 4 — APScheduler loop** — Wire `app/ingestion/scheduler.py` so the CLI runs automatically (daily tender poll, weekly awards back-fill, dossier download).
- **Understanding layer** — `FieldExtractor` using Claude tool-use to turn raw `tenders.raw_json` + `documents.text_content` into a clean `TenderProfile`. Post-extraction validator for sanity checks.
- **Phase 3 — Matching** — Hard-disqualifier rules, lazy-load embedding ensemble, semantic cosine scorer, budget/location/qualification rule sub-scorers, LR weights learner, `MatchingPipeline` orchestrator. Writes to `matches`.
- **Phase 3 — Seed `company_profiles`** — We need a starter pool of vendor capability profiles. Initially populated by hand from a curated list, later via scraping.
- **Phase 4 — Generation** — `EvidenceExtractor` finds dossier passages, `EmailDrafter` calls Claude with an evidence-only constraint (no hallucinated claims), `EmailValidator` checks output.
- **Phase 5 — Feedback + auth** — `POST /api/v1/feedback` endpoint, LR weight retraining job, basic multi-tenant auth.
- **Phase 6 — Agent** — `AgentController` exposes ingestion / matching / generation as Claude tools and drives multi-step workflows (see [docs/Notes.md](docs/Notes.md) for the recommended Planner-executor + Reflection-loop design).
- **Frontend integration** — Right now only `HomeView` makes a real backend call (`/health`). The other views (Tenders, Matches, Emails) are placeholders. We'll wire them up to the v1 API once the routers stop being stubs.
- **Minor follow-ups** — multi-page TED pagination (`iterationNextToken`) untested at scale; favicon 404; extend `LEGAL_SUFFIXES` to non-Latin scripts (Bulgarian `ООД`, Polish `Sp. z o.o.`, etc.); add `_` to entity-resolution punctuation set.

---

## 7. Summary — what you should now understand

1. **GTMAgent is a B2B lead-gen pipeline** for the EU construction-tech sector — pull tenders from TED → understand them with Claude → match against vendors → draft outreach emails → learn from feedback.
2. **The stack is Python 3.11 + FastAPI + Postgres (with pgvector) + Vue 3 + Vite + Tailwind**, all glued together with Docker for the database and Alembic for schema migrations.
3. **Three of the four ingestion jobs are live and verified.** We have 5 real tenders, 5 awards, 5 resolved companies, and 1 downloaded PDF dossier in the dev DB. Jobs 1, 2, and 3 of Phase 2 are done.
4. **The understanding, matching, generation, feedback, and agent layers are stubs** — empty files with the right names. That's where you come in.
5. **The database has 10 tables in 2 sub-graphs**: ingestion (`tenders`, `awards`, `companies`, `documents` — populated) and matching/emails (`company_profiles`, `matches`, `emails`, `feedback`, `embeddings` — empty, plus the `alembic_version` meta table).
6. **The TED API contract is empirically discovered, not documented** — read [CLAUDE.md §14 and §15](CLAUDE.md) before touching field names. Don't trust the official docs over the existing code.
7. **CI runs 3 jobs on every push**: backend pytest (57 tests), frontend lint+build, and an Alembic migration check against a fresh pgvector container.

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
docker ps
# Should show gtmagent-db-1 as "healthy"
```

### Step 5 — Set up the backend (Python venv)

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head            # applies migrations 0001, 0002, 0003
pytest tests -v                 # should show 57 passed
```

### Step 6 — Create the test database (one-time)

The dossier-downloader tests use a separate `gtm_test` database. Create it once:

```bash
docker exec gtmagent-db-1 psql -U gtm -d gtm -c "CREATE DATABASE gtm_test;"
docker exec gtmagent-db-1 psql -U gtm -d gtm_test -c "CREATE EXTENSION vector;"
```

Re-run `pytest tests -v` — all 57 tests should now pass on Postgres.

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

The other three views are intentional stubs right now (Tenders / Matches / Emails) — they render placeholder content because the matching/email pipelines aren't built yet.

### Step 10 — Smoke-test the TED ingestion (optional but satisfying)

From inside `backend/` with the venv active:

```bash
# Dry-run — fetches from TED, parses, doesn't write to DB:
python scripts/ted_smoke.py

# Live — writes ~5 tender rows:
python scripts/ted_smoke.py --live

# Then peek at the data:
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT ted_notice_id, buyer_country, deadline FROM tenders;"
```

### What to expect on first run

- **First `docker compose up -d db`** pulls the `pgvector/pgvector:pg16` image (~400 MB). Takes 30–60 seconds depending on connection.
- **First `pip install -r requirements-dev.txt`** downloads and builds wheels for ~40 packages. Takes 2–5 minutes. PyMuPDF and pgvector may compile from source briefly.
- **First `npm ci`** downloads ~300 MB into `node_modules/`. Takes 1–2 minutes. You may see deprecation warnings — they're benign (see [CLAUDE.md §11 — esbuild advisory](CLAUDE.md)).
- **First `alembic upgrade head`** runs 3 migrations in sequence and prints `INFO  [alembic.runtime.migration] Running upgrade ...` lines. Takes <2 seconds.
- **First `pytest tests -v`** — 57 tests, takes ~5–10 seconds. If any test fails on first run, the most likely cause is that you forgot Step 6 (create `gtm_test` database) — fix that and re-run.
- **Browser loads the Home view in ~300ms** with a clean "Backend status: ok" line. If that line says "Backend status: error" or never shows, your `uvicorn` isn't running or the Vite proxy can't reach it — check that uvicorn shows traffic in its log when you reload the page.

### Common Mac-specific gotchas

- **Port 5432 conflict** — If you have Postgres.app or `brew install postgresql` running, port 5432 will be taken and Docker silently loses. Symptom: "password authentication failed" errors that don't match the password you set. Fix: `brew services stop postgresql` (or quit Postgres.app), then re-run `docker compose up -d db`.
- **Python launcher** — On Mac there's no `py -3.11`; use `python3.11` directly. Once the venv is active (`source .venv/bin/activate`), plain `python` and `pip` resolve to the venv's 3.11.
- **Apple Silicon (M1/M2/M3)** — All our deps have ARM wheels. PyMuPDF, psycopg, and pgvector all build fine on Apple Silicon. No special flags needed.
- **`docker compose` vs `docker-compose`** — We use Compose v2 syntax (`docker compose`, with a space). If your `docker --version` is 20.x or older, upgrade Docker Desktop.

### When you're done for the day

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

- **Architecture / why-is-it-shaped-this-way**: [docs/architecture.md](docs/architecture.md) and [CLAUDE.md](CLAUDE.md).
- **Database tables**: [docs/Database_Explanation.md](docs/Database_Explanation.md).
- **TED API quirks / field names**: [CLAUDE.md §14 (CN) and §15 (CAN)](CLAUDE.md) — read these BEFORE editing any ingestion field list.
- **Smoke harnesses & DB cheatsheet**: [backend/scripts/README.md](backend/scripts/README.md).
- **Future-work design notes (agent layer, PDF scraping)**: [docs/Notes.md](docs/Notes.md).
- **Anything else**: ping Swaraj on the group chat.

Welcome aboard 🚧
