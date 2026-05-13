# GTM Agent

B2B lead-generation pipeline for the construction-tech sector. University group project — TUM CITHN2014.

## Stack
- **Backend**: Python 3.11 / FastAPI / Pydantic v2 / SQLAlchemy 2.x / Alembic
- **Database**: Postgres 16 + pgvector (`pgvector/pgvector:pg16`)
- **Frontend**: Vue 3 + TypeScript + Vite / Pinia / vue-router / Tailwind
- **Embeddings**: sentence-transformers ensemble (all-MiniLM-L6-v2, all-mpnet-base-v2, multilingual-e5-large) on CPU
- **LLM**: Claude Sonnet 4.6 (`claude-sonnet-4-6`) via Anthropic SDK
- **Scheduler**: APScheduler (in-process)
- **CI**: GitHub Actions

## Layout
```
backend/    FastAPI app, ingestion / understanding / matching / generation / agent modules
frontend/   Vue 3 + Vite SPA
docs/       Architecture notes
scripts/    DB init helpers
.github/    CI workflows
```

## Quick start

### Docker (everything)
```sh
cp backend/.env.example backend/.env
docker compose up --build
```
- API: http://localhost:8000/health
- Frontend: http://localhost:5173
- DB: `localhost:5432` (direct) and `localhost:6543` (pooled alias)

### Backend (local)
Create a Python 3.11 venv inside `backend/` — **not** the system default:
```sh
cd backend
py -3.11 -m venv .venv          # Windows
# or: python3.11 -m venv .venv  # macOS / Linux
.venv\Scripts\Activate.ps1      # Windows PowerShell
# or: source .venv/bin/activate # macOS / Linux
pip install -r requirements-dev.txt
cp .env.example .env
pytest tests -v
uvicorn app.main:app --reload
```

### Frontend (local)
```sh
cd frontend
npm install
npm run dev
```

### Migrations
```sh
cd backend
alembic upgrade head
```

## Connection strings
- `DATABASE_URL` — **pooled**, port 6543, used by the FastAPI app at runtime
- `DATABASE_URL_DIRECT` — **direct**, port 5432, used by Alembic only

Inside the Docker compose network both reduce to `db:5432`; the 6543 port is a host-side alias only.

## Roadmap
See [docs/architecture.md](docs/architecture.md) and the phase-tagged TODOs in source.
