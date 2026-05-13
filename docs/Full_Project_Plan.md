# Full Project Plan — GTM Agent
### Implementation, Schedule & Decision Guide

**Technical University of Munich (TUM)**  
School of Computation, Information and Technology  
Foundations and Applications of Generative AI (CITHN2014)

---

> **Companion documents:**
> - Project Proposal v2 — GTM Agent
> - Extensive Project Description — GTM Agent

---

## Document Conventions

| Marker | Meaning |
|--------|---------|
| 🔴 **[Claude suggestion]** | A recommendation not directly grounded in the team's source materials. Each can be accepted, adapted, or rejected. |
| 🟠 **[Group decision needed]** | Items where the team must make a deliberate choice before proceeding. |

---

## Table of Contents

1. [How to Read This Document](#1-how-to-read-this-document)
2. [Calendar Reality Check](#2-calendar-reality-check)
3. [Tech Stack — The Debate](#3-tech-stack--the-debate)
4. [APIs, Services and Accounts](#4-apis-services-and-accounts)
5. [Model Selection — Comparison Tables](#5-model-selection--comparison-tables)
6. [Project Architecture](#6-project-architecture)
7. [Step-by-Step Setup Guide](#7-step-by-step-setup-guide)
8. [Phase-by-Phase Plan](#8-phase-by-phase-plan)
9. [Milestones](#9-milestones)
10. [Test Cases & Evaluation](#10-test-cases--evaluation)
11. [Group Decision Points](#11-group-decision-points)
12. [Risk Register](#12-risk-register)
13. [Suggested Roles & Responsibilities](#13-suggested-roles--responsibilities)
14. [Schedule (Text Gantt)](#14-schedule-text-gantt)
15. [Closing Notes](#15-closing-notes)

---

## 1. How to Read This Document

This document is the third in a series. The **Project Proposal v2** sets out what we will build and why. The **Extensive Project Description** explains, section by section, how each part of the system works. This **Full Project Plan** answers the next set of questions: what stack, what models, what services, in what order, by when, against which tests, with which milestones, and where the team needs to make decisions. It is meant to be read with one tab open on the v2 proposal and one on the team Gantt chart.

The plan is organised in three layers. Layers can be read independently:

- **Decision layer (§3–5)** — Tech stack, services and accounts, model selection. Read first by the team lead and the people who will set up the repo.
- **Build layer (§6–7)** — Architecture and step-by-step setup. Read by everyone before week 1.
- **Execution layer (§8–14)** — Phases, milestones, tests, decisions, risks, roles, schedule. Re-read at the start of each phase.

---

## 2. Calendar Reality Check

The course has two hard deadlines: the **mid-term presentation** in the week of **1 June 2026**, and the **final presentation** in the last lecture of the semester. Documentation is submitted in a short buffer window after the final presentation. Today is **29 April 2026**.

### Working Backwards from Deadlines

| Phase | Calendar Week (Start) | Status / Target |
|-------|-----------------------|-----------------|
| Phase 0 — Bootstrap & architecture | 29 Apr 2026 | **Now** |
| Phase 1 — Data acquisition | 5 May 2026 | |
| Phase 2 — Tender understanding | 12 May 2026 | |
| Phase 3 — Matcher MVP | 19 May 2026 | |
| Phase 4 — Dashboard MVP + mid-term prep | 26 May 2026 | ⭐ MID-TERM week of 1 Jun |
| Phase 5 — Mid-term iteration | 8 Jun 2026 | |
| Phase 6 — Email generation + evidence layer | 15 Jun 2026 | |
| Phase 7 — Feedback loop & weight learner | 22 Jun 2026 | |
| Phase 8 — UAT (≥5 users) | 29 Jun 2026 | |
| Phase 9 — Polish, evaluation, pitch video | 6 Jul 2026 | |
| Phase 10 — Documentation push | 13 Jul 2026 | |
| Phase 11 — Final presentation + buffer | 20 Jul 2026 | ⭐ FINAL + submission |

Twelve calendar weeks total, with the mid-term roughly at the one-third mark. The plan below is sized to fit a 7-person team and assumes ~8–10 person-hours per member per week, which is the typical effort for a TUM module of this credit weight.

> 🔴 **[Claude suggestion]** If the team has external constraints (parallel exams, internships) that compress the calendar below this assumption, the first thing to drop is multilingual support (§3 of the v2 additions — keep English-only TED notices). The second thing to drop is the logistic-regression weight learner (§5 add. 7), keeping equal weights as a hard-coded prior. Both are listed in the v2 additions but are the most expendable for a first MVP.

---

## 3. Tech Stack — The Debate

### 3.1 Reframing the Question

The team has asked whether we should use **"Vue.ts + Nuxt"** or **"Python."** That framing mixes two questions. Vue/Nuxt is a frontend framework. Python is a backend language. They aren't competing for the same job; the project will need both. The real debates are:

1. **Backend language** — Python (FastAPI) vs. Node.js / TypeScript (Express, NestJS).
2. **Frontend framework** — Vue 3 + Vite vs. Nuxt 3 vs. React/Next vs. SvelteKit.
3. **Whether to unify them** — Use Nuxt server routes (Nitro) as the backend and skip Python entirely — yes/no.

---

### 3.2 Backend: Python vs. Node.js

| Criterion | Python (FastAPI) | Node.js / TS (NestJS) |
|-----------|------------------|----------------------|
| ML libraries | **Native:** sentence-transformers, scikit-learn, PyMuPDF, transformers, spaCy, dedupe, etc. | Most ML libs only have wrappers or none. Embeddings via API only. |
| LLM SDKs | **First-class:** openai, anthropic, google-genai all maintained. | Available, but feature-lagging the Python SDKs. |
| PDF extraction | PyMuPDF (fast), pdfplumber (tables), Unstructured. | Only thin wrappers; for 50–200 page dossiers this is a real liability. |
| Type safety | Type hints + mypy/pyright; weaker than TS. | Native TypeScript, stronger end-to-end typing. |
| Team familiarity | Used for university Python projects. | Used at work in TS/Vue. |
| Hireability of the codebase | Standard for ML teams in Europe. | Standard for web teams; rarer for ML. |

**Verdict: Python (FastAPI).** The matcher (§4 of the extensive doc) is built around Sentence-BERT, scikit-learn and PyMuPDF. These are Python-first ecosystems, and re-implementing them on Node.js would burn weeks for no gain. TypeScript on the frontend gets us most of the type-safety benefit without giving up the ML stack.

---

### 3.3 Frontend: Vue 3 + Vite vs. Nuxt 3 vs. Others

| Criterion | Vue 3 + Vite | Nuxt 3 | React / Next | SvelteKit |
|-----------|-------------|--------|-------------|-----------|
| Team familiarity | **High** (Vue at work) | High (Vue at work) | Lower | Low |
| Setup complexity | **Low** | Medium (SSR, server routes, Nitro) | Medium–high | Medium |
| SSR needed for this project? | **No** (private dashboard) | Adds complexity for no benefit | Same as Nuxt | Same |
| File-based routing | Manual (vue-router) — fine for a dashboard | Built-in | Built-in | Built-in |
| Build/run time | **Very fast** (Vite) | Fast | Slower historically | Fast |
| Component ecosystem | Vuetify, PrimeVue, shadcn-vue | Same as Vue 3 | Largest of all | Smaller |

**Verdict: Vue 3 + TypeScript + Vite.** The dashboard is a small, internal, private SPA. It does not need server-side rendering or SEO. Nuxt's headline features are wasted here, and its server-route layer (Nitro) cannot host the Python ML stack we need. Vue + Vite is the simplest tool that does the job and matches the team's existing Vue.ts skills.

---

### 3.4 Can Nuxt Server Routes Replace the Python Backend?

It is technically possible to put a thin Nuxt server-routes layer on top and call out to a Python ML microservice. That works. But it doubles the operational surface: two runtimes, two deployment pipelines, two sets of dependencies, and a network hop every time the frontend wants something the ML stack produced. For a 12-week student project with a private dashboard, the simpler architecture is one Python backend speaking JSON to one Vue + Vite SPA, behind a single reverse proxy.

> 🟠 **[Group decision needed]** Confirm the stack at the kick-off meeting in Phase 0. The recommended stack below is the default; if anyone has a strong reason to deviate (e.g., wants to learn Nuxt for portfolio reasons), that conversation belongs in week 1, not week 6.

---

### 3.5 Final Recommended Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Backend language | **Python 3.11+** | ML stack, LLM SDKs, PDF tools all native here. |
| Backend framework | **FastAPI + Pydantic** | Async, schema validation matches our LLM-extraction schema, OpenAPI docs free. |
| Worker / scheduler | **APScheduler** in-process for MVP; Celery + Redis if needed later | TED polling, dossier downloads, periodic retraining. |
| Database | **PostgreSQL 16 + pgvector extension** | Single store for relational + vector; see §5.5. |
| ORM / migrations | **SQLAlchemy 2.x + Alembic** | Industry standard, plays well with Pydantic. |
| Frontend framework | **Vue 3 + TypeScript** | Team skill, mature. |
| Frontend bundler | **Vite** | Fast iteration, no SSR overhead. |
| Frontend state | **Pinia** | Vue 3 idiomatic, tiny. |
| Frontend routing | **vue-router** | Standard. |
| Frontend styling | **TailwindCSS + Headless UI or shadcn-vue** | Skip bespoke CSS work; spend hours on the demo. |
| API contract | **OpenAPI from FastAPI; client types via openapi-typescript** | End-to-end typing without hand-written DTOs. |
| Containerisation | **Docker Compose** for local dev (api, db, frontend) | One command to get a teammate running. |
| CI | **GitHub Actions** | Free for public repos, sufficient for tests + lint. |
| LLM SDK | Provider-specific SDK (see §5.1) | Picked once the LLM provider is chosen. |
| Embeddings | **sentence-transformers (Python)** | Open-source, local; see §5.2. |
| PDF parsing | **PyMuPDF** primary; **pdfplumber** for table cases | See §5.3. |
| Web scraping | **Playwright** (Python) for JS-heavy sites; **httpx + selectolax** for static | See §5.4. |

> 🔴 **[Claude suggestion]** If the project leans into German-language tenders, also pin the spaCy German model (`de_core_news_lg`) for cheap NER on company-name candidates before sending them to the LLM.

---

## 4. APIs, Services and Accounts

Every external service the team will need to sign up for. **Sign up for these in week 1.** Some take a day or two for credentials, so doing this on day 1 prevents downstream blockages.

### 4.1 TED — EU Tenders Electronic Daily

Primary data source. **Free.** Fair-usage policy applies.

| Resource | Link |
|----------|------|
| Developer portal | https://developer.ted.europa.eu/home |
| Search API v2 | https://api.ted.europa.eu/v3/notices/search |
| Bulk downloads (eForms) | https://data.europa.eu/data/datasets?query=ted |

No API key required for read access, but the team should send a descriptive `User-Agent` and stay well under the published rate limits.

> 🔴 **[Claude suggestion]** Build the TED client behind a thin abstraction (a Python `TedClient` class). When TED migrates endpoint paths, only one file changes. This has happened twice in the last 18 months — it will happen again before the project ends.

---

### 4.2 LLM Provider

Pick **exactly one** for the MVP. Multi-provider abstractions sound clever; in a 12-week project they cost more than they save. See the comparison in §5.1.

| Provider | Sign-up link |
|----------|-------------|
| OpenAI | https://platform.openai.com/ |
| Anthropic | https://console.anthropic.com/ |
| Google AI Studio / Vertex | https://aistudio.google.com/ |
| Mistral | https://console.mistral.ai/ |

> 🟠 **[Group decision needed]** LLM provider choice. Decide in week 1 after §5.1. Document the cost ceiling per month and put a billing alert on the account.

---

### 4.3 Open-Source Embeddings (Hugging Face)

Models pulled from Hugging Face. No account strictly required for public models, but a free account avoids download throttling.

| Resource | Link |
|----------|------|
| Hugging Face | https://huggingface.co/ |
| all-MiniLM-L6-v2 | https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 |
| all-mpnet-base-v2 | https://huggingface.co/sentence-transformers/all-mpnet-base-v2 |
| multilingual-e5-large | https://huggingface.co/intfloat/multilingual-e5-large |
| BAAI/bge-m3 | https://huggingface.co/BAAI/bge-m3 |

---

### 4.4 Web Search Fallback

| Provider | Link | Notes |
|----------|------|-------|
| Bing Web Search API | https://www.microsoft.com/en-us/bing/apis/bing-web-search-api | Safer institutional choice |
| Brave Search API | https://brave.com/search/api/ | Privacy-focused alternative |
| Tavily | https://tavily.com/ | Purpose-built for LLM agents |

> 🔴 **[Claude suggestion]** Tavily is purpose-built for LLM agents and returns clean snippets with source URLs. Bing is the safer institutional choice. For an MVP, Tavily's lower-friction onboarding wins. Free tier is enough for the project.

---

### 4.5 PDF Parsing & Multilingual

| Library | Link |
|---------|------|
| PyMuPDF | https://pymupdf.readthedocs.io/ |
| pdfplumber | https://github.com/jsvine/pdfplumber |
| DeepL API (optional) | https://www.deepl.com/pro-api |

> DeepL only if the team decides to translate dossier PDFs into English instead of relying on multilingual embeddings.

---

### 4.6 Database & Vectors

| Resource | Link |
|----------|------|
| PostgreSQL | https://www.postgresql.org/ |
| pgvector extension | https://github.com/pgvector/pgvector |

---

### 4.7 Optional Sectoral Registers (per CPV choice)

| Register | Link |
|----------|------|
| EUDAMED (MedTech) | https://ec.europa.eu/tools/eudamed/ |
| ENISA (Cybersecurity) | https://www.enisa.europa.eu/ |
| OpenStreetMap (geographic verification) | https://www.openstreetmap.org/ |
| GitHub API (IT/Cyber stack verification) | https://docs.github.com/rest |

---

### 4.8 Hosting

For an MVP the project does not need to be deployed at all — a local `docker-compose` run is enough for the demo.

| Layer | Option A | Option B |
|-------|----------|----------|
| Backend | [Render](https://render.com/) | [Railway](https://railway.com/) |
| Frontend | [Vercel](https://vercel.com/) | [Netlify](https://www.netlify.com/) |
| Database | [Neon](https://neon.com/) | [Supabase](https://supabase.com/) |

> 🔴 **[Claude suggestion]** Skip remote hosting until Phase 7 at the earliest. The grading rubric asks for a live demo, not a publicly hosted URL. Local demos at the presentation are completely acceptable and save the team a week of devops work.

---

## 5. Model Selection — Comparison Tables

> All comparisons below should be sanity-checked against the providers' own pricing pages before the team commits, because pricing changes faster than this document does. The qualitative ranking is more durable than the prices.

### 5.1 LLM Provider

**Used for:** structured field extraction from tenders, company profile extraction, evidence-grounded email drafting, entity-resolution tie-breaking.  
**Throughput:** low (a few hundred extractions per day on the MVP).  
**Quality requirement:** high — this is the only stage where free-form text becomes our schema.

| Provider / Family | Strengths | Weaknesses | Cost Class | Recommended For |
|-------------------|-----------|------------|------------|-----------------|
| OpenAI — GPT-5 / GPT-4o / o-series | Mature SDK, strong JSON mode and function calling, good on legalese | Closed; pricing tiered | Medium | Default if the team has no other constraint |
| Anthropic — Claude 4.x (Sonnet / Opus / Haiku) | Long context (200k+), strong on structured output and instruction-following | Closed; Sonnet/Opus more expensive than mid-tier OpenAI | Medium–High | Long-dossier extraction; evidence-grounded drafting |
| Google — Gemini 2.5 Pro / Flash | Very long context (1M tokens), Flash tier is cheap | Ecosystem less mature; safety filters can be aggressive on tender legalese | Low–Medium | Cost-sensitive bulk extraction |
| Mistral — Large / Medium | EU-hosted (data-residency story for TUM) | Smaller ecosystem, function calling less mature | Medium | If data residency becomes a topic in the GenAI Safety report |
| Open-source self-hosted — Llama 3.x, Qwen 2.5/3, DeepSeek-V3 | Free at scale, no rate limits, full control | Need a GPU; ops burden | Low (after fixed cost) | **Not recommended** for a 12-week project |

> 🔴 **[Claude suggestion]** Default to one of: Claude Sonnet 4.x, GPT-4o, or Gemini 2.5 Pro. Any of the three is sufficient. The factor most likely to matter is **reliable JSON-schema-conformant output**, which all three handle well. Pick the one whose API key the team already has.

---

### 5.2 Embedding Models (Open Source, Ensemble)

**Used for:** the semantic similarity sub-score in the matcher (see §4.3 of the extensive doc).  
All listed models are MIT/Apache and **run locally** on CPU or a small GPU.

| Model | Languages | Dim | Speed (CPU, relative) | Quality (MTEB-tier) | Recommended Use |
|-------|-----------|-----|-----------------------|--------------------|--------------| 
| `sentence-transformers/all-MiniLM-L6-v2` | English | 384 | Very fast (1.0× baseline) | Mid | Recall stage; cheap reranker on every requirement–portfolio pair |
| `sentence-transformers/all-mpnet-base-v2` | English | 768 | ~3× slower | High (English) | Precision stage on the top-K from MiniLM |
| `intfloat/multilingual-e5-large` | Multilingual (EU 24) | 1024 | ~6× slower | High (multilingual) | Cross-language tender↔company matching |
| `BAAI/bge-m3` | Multilingual + dense/sparse | 1024 | ~6× slower | Very high (multilingual) | Strong drop-in alternative to e5-large |
| `intfloat/e5-small-v2` | English | 384 | ~1.5× baseline | Mid–High | Backup recall model if MiniLM is rejected on quality |

**Ensemble recommendation:** MiniLM-L6-v2 (recall) → mpnet-base-v2 (English precision) + multilingual-e5-large (multilingual). Z-score-normalise per model, then average.

> 🟠 **[Group decision needed]** Whether to substitute `bge-m3` for `multilingual-e5-large`. bge-m3 is newer and benchmarks slightly higher. Decide once Phase 2 is running and you can compare both on real tender pairs from your CPVs.

---

### 5.3 PDF Extraction

| Library | Strengths | Weaknesses | License |
|---------|-----------|------------|---------|
| **PyMuPDF (fitz)** | Fast, faithful text extraction, hyperlink extraction, page rendering | AGPL by default; commercial license needed for closed-source use | AGPL / commercial |
| **pdfplumber** | Excellent for tables and rule-based layout | Slower than PyMuPDF on plain text | MIT |
| **Unstructured** | Auto-routing to OCR for scanned docs, ML-based section detection | Heavy dependency footprint | Apache 2.0 |
| **pypdf** | Pure Python, simple | Weak on real-world dossiers | BSD |

**Verdict:** PyMuPDF as the primary extractor (fast, links, page numbers — we need page numbers for `evidence_span`). pdfplumber as a secondary path when a tender has heavy tables. AGPL is fine for a course project; we are not shipping the code commercially.

---

### 5.4 Web Scraping

| Library | Best For | Headless Browser? | Notes |
|---------|----------|-------------------|-------|
| **httpx + selectolax** | Static HTML, fast, low ceremony | No | Default for company About / Services pages |
| **Playwright (Python)** | JS-heavy SPA company sites | Yes | Slower; only when httpx fails |
| **Scrapy** | Large crawls with queueing | Optional | Overkill for our scope |
| **Crawlee (Python)** | Modern, Apify-style queue | Optional | Promising but extra deps |

**Verdict:** httpx + selectolax first; fall through to Playwright on detection of empty DOM after fetch.

---

### 5.5 Database & Vector Store

| Option | Setup Complexity | Vector Ops | Cost | Recommended |
|--------|-----------------|------------|------|-------------|
| **PostgreSQL + pgvector** | Low (one extension) | Cosine, L2, inner product, HNSW index | Free (self-hosted) or Neon/Supabase free tier | ✅ Yes — default for the MVP |
| Qdrant | Medium (separate service) | Best-in-class vector ops | Free self-hosted | Only if vector volume exceeds ~10M embeddings |
| Weaviate | Medium–high | Strong, with built-in modules | Free self-hosted | No — too heavy for our scale |
| Pinecone | Low (managed) | Strong | Paid only after free tier | No — vendor lock-in for no benefit at this scale |

**Verdict:** Postgres + pgvector. Same database for relational and vector data, single backup story, single migration story.

---

## 6. Project Architecture

### 6.1 High-Level System

Five logical layers, each independently deployable but starting in a **single FastAPI process** for the MVP:

| Layer | Responsibility |
|-------|---------------|
| **Ingestion** | TED Search client (Contract Notices), TED Awards client (historical), dossier downloader, web-search fallback, company-website scraper |
| **Understanding** | Tender section extractor (LLM + schema), company profile extractor (LLM + schema), entity resolution |
| **Matching** | Disqualifier filter, semantic similarity (multi-model embedding ensemble), rule-based scoring, past-win feature, logistic-regression weight learner, score-explanation generator |
| **Generation** | Evidence extractor, constrained LLM email drafter, post-validator |
| **Interface** | Vue dashboard, REST API, feedback capture, weight-override UI |

---

### 6.2 Data Flow (One Tender, End to End)

```
1. Scheduler triggers TED poll → new Contract Notice JSON
2. Ingestion downloads dossier PDFs → documents table
3. Understanding extracts structured Tender record → tenders table
4. Discovery: query awards table for past winners on same CPV / buyer
   → fallback: web_search if too few candidates
5. For each candidate company: scrape → profile extract → company_profiles table
6. Matching:
   a. disqualifier filter
   b. embed requirements & portfolio → embeddings table
   c. semantic + rule + past-win sub-scores
   d. weighted aggregate → matches table (with explanation)
7. Top-K surfaced on dashboard
8. User reviews, slides weights → client-side recompute
9. User clicks Generate Email → evidence extractor → LLM drafter → emails table
10. User thumbs up/down → feedback table → nightly retrain of LR weights
```

---

### 6.3 Repository Layout

```
gtm-agent/
├── backend/                # Python FastAPI
│  ├── app/
│  │  ├── api/             # FastAPI routers
│  │  ├── ingestion/       # ted_client, awards_client, scraper
│  │  ├── understanding/   # extractors, schemas
│  │  ├── matching/        # disqualifier, embedder, rules, lr_weights
│  │  ├── generation/      # evidence, drafter, validator
│  │  ├── db/              # SQLAlchemy models, migrations
│  │  └── main.py
│  └── tests/
├── frontend/               # Vue 3 + Vite + TS
│  ├── src/
│  │  ├── components/
│  │  ├── stores/           # Pinia
│  │  ├── views/
│  │  └── api/              # generated openapi-typescript client
│  └── vite.config.ts
├── docker-compose.yml
├── .github/workflows/ci.yml
├── docs/                   # design notes, this doc, ADRs
└── README.md
```

---

## 7. Step-by-Step Setup Guide

This is what **one person** does on day 1 of Phase 0. Once it works on their machine, they push to the repo and the rest of the team checks out and runs `docker compose up`.

### 7.1 Prerequisites

- Python 3.11+ and pip
- Node.js 20+ and npm
- Docker Desktop (for Postgres + pgvector locally)
- Git, a GitHub account, and an SSH key set up
- API keys for the chosen LLM provider and (optionally) Tavily/Bing

---

### 7.2 Repository Bootstrap

```bash
# create the repo on GitHub first, then:
git clone git@github.com:<org>/gtm-agent.git
cd gtm-agent
mkdir -p backend frontend docs
touch README.md docker-compose.yml
```

---

### 7.3 Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn[standard] pydantic[email] sqlalchemy alembic \
    psycopg[binary] pgvector httpx selectolax pymupdf pdfplumber \
    sentence-transformers scikit-learn apscheduler python-dotenv

# pick ONE LLM SDK (example: anthropic)
pip install anthropic

# freeze
pip freeze > requirements.txt
```

---

### 7.4 Frontend

```bash
cd ../frontend
npm create vite@latest . -- --template vue-ts
npm install
npm install pinia vue-router@4
npm install -D tailwindcss @tailwindcss/forms postcss autoprefixer \
    openapi-typescript prettier eslint @vue/eslint-config-typescript
npx tailwindcss init -p
```

---

### 7.5 Database (docker-compose)

```yaml
# docker-compose.yml at repo root
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: gtm
      POSTGRES_PASSWORD: gtm
      POSTGRES_DB: gtm
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes:
  pgdata:
```

```bash
docker compose up -d db

# create extension
psql postgres://gtm:gtm@localhost:5432/gtm -c "CREATE EXTENSION vector;"
```

---

### 7.6 Secrets & Environment

```bash
# backend/.env   (gitignored — never commit real keys)
DATABASE_URL=postgresql+psycopg://gtm:gtm@localhost:5432/gtm
LLM_API_KEY=sk-...
LLM_PROVIDER=anthropic
TAVILY_API_KEY=tvly-...        # optional
ALLOWED_CPV_CODES=45000000-7,72000000-5,09330000-1
```

> 🔴 **[Claude suggestion]** Add `.env.example` to the repo with all keys but no values. New teammates copy it to `.env` and fill in their own credentials. Never commit real keys.

---

### 7.7 First Run

```bash
# terminal 1 — backend
uvicorn app.main:app --reload --port 8000

# terminal 2 — frontend
cd frontend && npm run dev   # http://localhost:5173
```

---

### 7.8 CI (GitHub Actions, week 1)

Minimum bar at the end of Phase 0: a CI workflow that runs on every PR and does:

1. `pytest backend/tests`
2. `npm run lint && npm run build` in frontend
3. Alembic migration sanity check

No CD needed for the MVP.

---

## 8. Phase-by-Phase Plan

> Each phase has: scope, deliverable, exit criteria, and what **NOT** to do.

---

### ⚙️ Phase 0 — Bootstrap & Architecture *(Week of 29 Apr 2026)*

**Scope:** Stack confirmed, repo bootstrapped, accounts created, architecture diagram approved by the team. Pick CPV scope and LLM provider.

**Deliverable:** `docker compose up` runs a FastAPI hello-world + Vue page + empty Postgres+pgvector DB. CI green. Architecture diagram in `/docs`.

**Exit criteria:** Every team member can clone the repo and run the stack locally in under 10 minutes.

**Do NOT:** Start writing prompts or scrapers in Phase 0. Spending the first week on plumbing pays off; spending it on premature features does not.

> 🟠 **[Group decision needed]** Final CPV scope (2–3 codes). LLM provider. Hosted vs local for the demo.

---

### 📥 Phase 1 — Data Acquisition *(5 May)*

**Scope:** TED Contract Notices client, TED Award Notices client, dossier downloader, raw storage in `tenders` + `awards` tables. No LLM yet.

**Deliverable:** CLI command `python -m app.ingestion poll` ingests last 7 days of notices for the chosen CPVs into Postgres. Awards back-fill of 24 months.

**Exit criteria:** ≥ 200 contract notices and ≥ 5,000 award notices in the DB. Idempotent re-runs (no duplicates).

> 🔴 **[Claude suggestion]** Implement entity resolution as a thin first pass in Phase 1 (just lower-cased + punctuation-stripped name match) so awards are attributable to canonical companies. The LLM tie-breaker is a Phase 7 polish item.

---

### 📄 Phase 2 — Tender Understanding *(12 May)*

**Scope:** LLM-based extractor over JSON + dossier PDFs, producing the structured Tender object from §3.1 of the extensive doc. Map-reduce summarisation for long PDFs.

**Deliverable:** 90% of polled tenders have a complete structured record (deadline, budget, `technical_requirements` with `evidence_span`, eligibility, evaluation criteria).

**Exit criteria:** Schema validation pass-rate ≥ 90% on a held-out sample of 50 tenders, manually labelled by the team.

**Do NOT:** Tune the prompts beyond the 90% bar. Phase 2 stops at "good enough for Phase 3."

---

### 🧮 Phase 3 — Matcher MVP *(19 May)*

**Scope:** Disqualifier filter, single-model embedding similarity (MiniLM only at this stage), rule-based budget/geo/cert scoring, hard-coded equal weights. Score-explanation generator.

**Deliverable:** API endpoint `POST /tenders/{id}/match` returns top-K candidates with sub-scores and a textual explanation.

**Exit criteria:** Backtesting: for 20 randomly chosen historical tenders, the actual winner is in the top-10 for at least **50%** of cases.

> 🔴 **[Claude suggestion]** Resist adding the embedding ensemble or the LR weight learner here. They go in Phase 6/7. Phase 3 must be runnable end-to-end before mid-term.

---

### 🖥️ Phase 4 — Dashboard MVP + Mid-Term Prep *(26 May)*

**Scope:** Three-column workflow (Tenders → Lead Analysis → placeholder for Email). Weight sliders with client-side recompute. Score-explanation panel. Mid-term slides and rehearsal.

**Deliverable:** Live demo on a single laptop: pick a tender, see top-5, slide a weight, ranking changes. Slides for the mid-term presentation.

**Exit criteria:** Mid-term presentation delivered (week of 1 Jun).

**Mid-term presentation — what to show:** Per the rubric: project vision, team roles, project timeline (Gantt), system architecture, current progress. The 4-minute demo = pick a tender → show extracted sections → show top-5 matches with explanations → nudge a slider → close. Do **not** show email generation yet (it isn't built); be honest that it is the next phase.

---

### 🔁 Phase 5 — Mid-Term Iteration *(8 Jun)*

**Scope:** Apply mid-term feedback. Add the embedding ensemble (mpnet + multilingual-e5). Strengthen the schema validator. Tighten the disqualifier filter.

**Deliverable:** Backtest hit-rate (winner in top-10) improves to ≥ **65%**.

---

### ✉️ Phase 6 — Email Generation + Evidence Layer *(15 Jun)*

**Scope:** Evidence extractor (deterministic). Constrained LLM drafter. Post-validator (every named claim must trace to an evidence span). Email UI in the dashboard with citations.

**Deliverable:** End-to-end pipeline: tender → top-5 → click candidate → generate email → every claim is hyperlinked to its source span.

---

### 🤖 Phase 7 — Feedback Loop & Weight Learner *(22 Jun)*

**Scope:** Thumbs-up/down on emails and on matches; logistic-regression training script using award history as ground truth; nightly retrain; weight-override logging.

**Deliverable:** `python -m app.matching.train_weights` prints AUC on a held-out set and writes the new coefficients to the DB. Dashboard shows the recommended weights from the trained model.

---

### 👥 Phase 8 — User Acceptance Testing *(29 Jun)*

**Scope:** Recruit ≥ 5 users matching the target audience (sales / business-development roles in construction-tech / IT-services / renewable-energy). Run a structured think-aloud session per the rubric Document 3 template.

**Deliverable:** UAT data in a single CSV; `user_case_study.md`, `user_survey.md`, `results.md` drafts in `/docs`.

> 🔴 **[Claude suggestion]** Recruit users via TUM's entrepreneurship network (UnternehmerTUM, XPRENEURS) and direct outreach to TUM CIT alumni in sales roles. Five users is the rubric minimum; aim for seven so you can drop two if their feedback is unusable.

---

### 🎯 Phase 9 — Polish, Evaluation, Pitch Video *(6 Jul)*

**Scope:** Bug-fix sprint based on UAT. Final backtesting numbers. Record the ~60s pitch video required by rubric Document 2.

**Deliverable:** Pitch video (1080p, scripted voiceover, live software demo). Final evaluation table for the Project Management Report.

---

### 📝 Phase 10 — Documentation Push *(13 Jul)*

**Scope:** All four deliverable docs written, peer-reviewed inside the team, formatted to the page limits.

| Document | Page Limit |
|----------|-----------|
| User Guide | ≤ 5 pages |
| Project Management Report | ≤ 8 pages (with Gantt and prompt-engineering section) |
| UAT Report | ≤ 3 pages |
| GenAI Safety & Reflection | ≤ 3 pages |

---

### 🏁 Phase 11 — Final Presentation + Buffer *(20 Jul)*

**Scope:** Final presentation rehearsal, MVP live demo, Q&A prep. Documentation submission.

**Deliverable:** Final presentation delivered. All four documents submitted via Moodle. Peer-review forms submitted individually via Google Form (per rubric).

---

## 9. Milestones

| # | Milestone | Due | Done When |
|---|-----------|-----|-----------|
| M1 | Repo + CI green + accounts ready | End of Phase 0 | `docker compose up` runs; CI passes a trivial test |
| M2 | TED ingestion end-to-end | End of Phase 1 | ≥ 200 notices + ≥ 5,000 awards stored |
| M3 | Structured tender records | End of Phase 2 | ≥ 90% schema-valid on labelled sample of 50 |
| M4 | Matcher MVP | End of Phase 3 | Backtest winner-in-top-10 ≥ 50% |
| M5 | ⭐ Mid-term presentation | Week of 1 Jun | Demo delivered; rubric mid-term marks recorded |
| M6 | Embedding ensemble live | End of Phase 5 | Top-10 ≥ 65% |
| M7 | Email + evidence layer | End of Phase 6 | Every claim in email traces to a source span |
| M8 | Trained weight learner | End of Phase 7 | AUC reported; dashboard reflects trained weights |
| M9 | UAT complete | End of Phase 8 | ≥ 5 users; data analysed |
| M10 | Pitch video recorded | End of Phase 9 | Video file + script under `/docs` |
| M11 | Docs ready | End of Phase 10 | All four docs within page limits, peer-reviewed |
| M12 | ⭐ Final presentation + submission | End of Phase 11 | Presentation delivered; Moodle submission confirmed |

---

## 10. Test Cases & Evaluation

Tests are split into four families. The first two are **continuous**; the second two are run at **phase boundaries**.

### 10.1 Unit Tests *(Continuous)*

| Test File | What It Covers |
|-----------|----------------|
| `test_ted_client.py` | Mock the TED HTTP layer; assert the parser produces expected fields for a fixture notice |
| `test_pdf_extract.py` | Fixture dossier PDFs of varying lengths; assert extracted text length and that hyperlinks are detected |
| `test_schema.py` | Every produced Tender object passes Pydantic validation |
| `test_disqualifier.py` | Blacklisted company removed; geographic mismatch removed; small company on big tender removed |
| `test_rules.py` | Budget overlap function across boundary cases (full overlap, partial, none) |

---

### 10.2 Integration Tests *(Continuous)*

- End-to-end on a frozen fixture tender: ingest → extract → match → generate email; assert non-trivial output and schema validity at every step.
- Schema-stable contract: regenerate the OpenAPI client and ensure the frontend type checks pass.

---

### 10.3 Backtesting *(Every Phase Boundary, Weeks 3+)*

**Setup:** For each historical Award Notice, reconstruct the world as of the day the corresponding Contract Notice was issued (i.e., exclude any data that came after that date). Run the matcher. Record where the actual winning company ranks in our shortlist.

**Metrics:**

| Metric | Description |
|--------|-------------|
| Top-1 accuracy | % of tenders where the actual winner is our #1 recommendation |
| Top-5 / Top-10 accuracy | % where the winner is in the top 5 / 10 |
| MRR (mean reciprocal rank) | 1/rank of the actual winner, averaged |
| Disqualifier false-positive rate | % of actual winners filtered out by disqualifiers (must be near 0) |

**Targets across phases:**

| Metric | Phase 3 (MVP) | Phase 5 (Post-Mid-Term) | Phase 9 (Final) |
|--------|:---:|:---:|:---:|
| Top-10 accuracy | ≥ 50% | ≥ 65% | ≥ 75% |
| Top-5 accuracy | ≥ 30% | ≥ 45% | ≥ 55% |
| Top-1 accuracy | — | — | ≥ 25% |
| Disqualifier FP rate | 0 (manual) | ≤ 2% | ≤ 1% |

---

### 10.4 UAT Scenarios *(Phase 8)*

Five users, each given the same three scripted scenarios. Time to complete and qualitative feedback are recorded.

1. Find a live tender in your sector, identify the top-3 most promising candidates, and explain why.
2. Adjust the matcher weights so that companies you know to be too small no longer rank highly.
3. Generate an outreach email for one of the top-3, edit it, and rate the draft. Verify that every claim in the draft is hyperlinked to its source.

> 🔴 **[Claude suggestion]** Recruit a sixth user who is a sales person who has NEVER seen the system, and run scenario 1 as a cold-start test. The User Guide (rubric doc 1) is graded partly on how a fresh reader experiences it; this is a very cheap proxy.

---

### 10.5 Acceptance Criteria for Each MVP Slice

| Slice | Accepted When |
|-------|---------------|
| Tender ingested | Structured Tender record passes schema validation |
| Match surfaced | All sub-scores are present (no nulls) |
| Email draftable | Post-validator finds zero unsupported named claims |
| Weight override applied | Recomputed score and rationale are visible to the user (no silent updates) |

---

## 11. Group Decision Points

> Decisions the team must make explicitly. Each one belongs in **a meeting, not a Slack thread.**

| # | Decision | Latest By | Owner Role |
|---|----------|-----------|------------|
| D1 | CPV scope: which 2–3 sectors? | End of Phase 0 | Project lead |
| D2 | LLM provider | End of Phase 0 | Backend lead |
| D3 | Default weights at Phase 3 (before LR is trained) | Start of Phase 3 | Matcher lead |
| D4 | Embedding ensemble: keep e5-large or swap to bge-m3 | Start of Phase 5 | Matcher lead |
| D5 | How many candidates per tender (top-K) on the dashboard | Start of Phase 4 | Frontend lead, validated by UAT |
| D6 | Web search vendor (Tavily vs Bing vs none) | Start of Phase 1 | Backend lead |
| D7 | Restricted-dossier policy ("open in browser" pattern from §2.5 of the extensive doc) | Start of Phase 1 | Backend lead + GenAI Safety lead |
| D8 | Multilingual scope: full 24 languages or English-only first | Start of Phase 5 | Project lead |
| D9 | UAT user list and recruitment channel | Start of Phase 8 | UAT lead |
| D10 | What to keep vs cut from §5 v2 additions if the calendar slips | Continuously | Project lead |
| D11 | Hosted demo or local-only at Final Presentation | Start of Phase 9 | Project lead |

---

## 12. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|:----------:|:------:|------------|
| R1 | TED API endpoint paths change mid-project | Medium | Medium | Wrap TED in a single client class; pin tests against fixtures |
| R2 | LLM extraction below 90% schema-valid on dossiers | Medium | High | Map-reduce + per-field re-prompt; fall back to deterministic regex on cover-page fields |
| R3 | Backtest hit-rate stalls below targets | Medium | High | Phase-5 ensemble buys headroom; if still short, re-scope success metric to top-10 only and document honestly |
| R4 | Cannot recruit ≥ 5 UAT users | Low–Medium | **High (rubric)** | Start recruiting in Phase 6, not Phase 8. Use TUM entrepreneurship network |
| R5 | Team member becomes unavailable | Medium | Medium | All work in PRs against main; no single owner of any module |
| R6 | Dossier behind login walls, blocks tender flow | High (in construction CPV) | Medium | "Restricted" status + manual-open UX; do not build credentialed scraping |
| R7 | LLM costs run away during Phase 6 | Medium | Medium | Per-key budget alert at $50; cache extraction outputs in DB; never reprocess unchanged tenders |
| R8 | Hallucinated claims in emails reach the demo | Medium | **High (credibility)** | Post-validator is a hard gate, not a warning. Emails fail loudly when validation fails |
| R9 | Scope creep from Mei/Trinh ideas (Vision-LLMs, Neo4j, consortium detection) | High | Medium | Catalogue these as Future Work in the Project Management Report; do not commit to MVP |
| R10 | Documentation written in the last 48 hours | High (default) | **High (15+ rubric points)** | Phase 10 is dedicated; one doc per pair, peer-reviewed inside the team in Phase 11 |

---

## 13. Suggested Roles & Responsibilities

Seven team members. Each has one primary role and one shared secondary role. Names in the v2 proposal; assign at the kick-off meeting.

| Role | Primary Responsibility | Touches Phases |
|------|----------------------|----------------|
| **Project Lead / Architect** | Coordinates, owns the timeline, runs the kick-off and the mid-term/final rehearsals, owns decisions D1, D8, D10, D11 | 0, 4, 9, 11 |
| **Backend / Ingestion Lead** | TED clients, awards back-fill, scraper, FastAPI scaffolding. Owns D2, D6, D7 | 0–3, 5 |
| **Matcher / ML Lead** | Disqualifier, embedding ensemble, rules, LR weight learner, score explanations. Owns D3, D4 | 3, 5–7 |
| **LLM / Extraction Lead** | Prompt engineering, schema validation, evidence extractor for emails. Co-owns the GenAI Safety report | 2, 6 |
| **Database / Backend #2** | SQLAlchemy models, migrations, pgvector indexing, performance | 0–2, 7 |
| **Frontend Lead** | Vue dashboard, weight sliders, evidence panel, email UI. Owns D5 | 4, 6, 8 |
| **UAT / Documentation Lead** | Recruits users, runs UAT, owns D9. Coordinates the four deliverable docs in Phase 10 | 8, 10 |

> 🔴 **[Claude suggestion]** Pair-program across boundaries: Backend × LLM in Phase 2, Matcher × Frontend in Phase 4. This both raises the bus factor and saves the inevitable interface-misunderstanding rewrites that happen when modules are built in isolation.

---

## 14. Schedule (Text Gantt)

> ■ = active workstream &nbsp;&nbsp; ⭐ = milestone

| Workstream | W1 | W2 | W3 | W4 | W5 | W6 | W7 | W8 | W9 | W10 | W11 | W12 |
|------------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:---:|:---:|:---:|
| Bootstrap & arch | ■ | | | | | | | | | | | |
| TED ingestion | ■ | ■ | ■ | | | | | | | | | |
| Tender understanding | | ■ | ■ | ■ | | | | | | | | |
| Matcher MVP | | | | ■ | ■ | | | | | | | |
| Dashboard | | | | | ■ | ■ | ■ | ■ | | | | |
| Mid-term prep | | | | | ■ | ⭐ | | | | | | |
| Embedding ensemble | | | | | | ■ | ■ | | | | | |
| Email + evidence | | | | | | | ■ | ■ | | | | |
| Feedback / LR weights | | | | | | | | ■ | ■ | | | |
| UAT | | | | | | | | | ■ | ■ | | |
| Polish + pitch video | | | | | | | | | | ■ | ■ | |
| Documentation | | | | | | | | | | | ■ | ■ |
| Final presentation | | | | | | | | | | | | ⭐ |

---

## 15. Closing Notes

Three principles to keep returning to when the work gets messy:

1. **Phase exit criteria are real.** If a phase's exit criteria are not met, the next phase does not start. The instinct will be to push everything into the next sprint and ship two phases at once. Resist it.

2. **Novelty lives in §4 of the extensive doc.** The hybrid matcher is what differentiates this from a wrapper. Whenever a teammate proposes "let's just ask the LLM," the answer is to point them at the matcher layer.

3. **Documentation is a fifth of the grade.** Phase 10 exists for a reason. The four documents at ≤5/8/3/3 pages are not a side quest; they are 55 of the 100 marks.

---

*End of plan.*
