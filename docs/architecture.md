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

### Embeddings — sentence-transformers ensemble, CPU-only
Three local models:
- `all-MiniLM-L6-v2` (384-d, fast)
- `all-mpnet-base-v2` (768-d, accurate)
- `multilingual-e5-large` (1024-d, multilingual)

All loaded lazily on first use. No GPU dependency.

### LLM — Claude Sonnet 4.6 via Anthropic SDK
Model id: `claude-sonnet-4-6`. Used for:
- structured field extraction (tool-use enforced schema)
- evidence-grounded email drafting
- multi-step agent orchestration (Agent Controller)

### Frontend — Vue 3 + Vite + Pinia + Tailwind
TypeScript throughout. `openapi-typescript` will generate the API client
from the FastAPI schema once the v1 routes are real.

### Scheduling — APScheduler in-process
Lightweight, no broker dependency. Daily TED pull, weekly award back-fill.

### CI — GitHub Actions
Three jobs on every push / PR: backend pytest, frontend lint + build,
Alembic upgrade check against a real pgvector service container.

## Deferred / not in scope yet
- Authentication & multi-tenant separation — Phase 5
- Playwright E2E — install only when needed
- DeepL / translation — out of scope; multilingual handled by the
  multilingual-e5 embedder
- Background queue (Celery, RQ) — not needed at current scale
