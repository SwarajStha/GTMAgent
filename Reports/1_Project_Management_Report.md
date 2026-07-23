# Project Management Report — GTM Agent

**Technical University of Munich (TUM)**
School of Computation, Information and Technology
Course: *Foundations and Applications of Generative AI* (CITHN2014)
Project 4 — **GTM Agent**

> **Document status:** DRAFT / structural backbone for the final submission.
> Page budget (rubric): **≤ 8 pages** excluding title, table of contents, and references.
> Sections marked **`[NEEDS INPUT]`** require team-supplied facts; sections marked
> **`[TEAM DECISION]`** require an explicit team call before submission. Remove all
> such callouts (and this status block) before the final version.

> **── Sync update 2026-07-23: aligned to the current codebase (post-G20/G23/G25/G27) ──**
> This report previously reflected the 2026-07-01 state. The items below were edited
> to match the code as of the 2026-07-05 sprint. **Peers: review each item, then
> delete this whole block before submission.**
> - **§1.3 & §7 (Evaluation)** — real, reproducible backtest numbers now exist
>   (model retrained on 80% of awards, 2026-07-05): **Hit@1 44.2% · Hit@3 54.0% ·
>   Hit@5 57.6%** (500 held-out awards, winner-in-pool). Filled in; several
>   `[NEEDS INPUT]` numbers are now resolved. *Still open for the team:* a Top-10
>   figure (current backtest reports up to Hit@5) and MRR, if you want them — extend
>   `exports_ml_pipeline.py` eval to Hit@10.
> - **§6.1** — added the runtime scheduler toggle + ops-command console (G27);
>   progress-snapshot date moved to 2026-07-05.
> - **§4.4 / §5** — test count ~227 → ~346; migrations `0001`→`0015`; scheduler is
>   no longer a stub; dropped the deleted standalone lead-scoring demo (G25);
>   added the train/serve feature-contract drift guard (G20).
> - **§3.2** — the Understanding layer is described as **shipped** (it was still
>   labelled a "stub", contradicting §6.1 which lists it Done via G11).
> - **§3.3** — table count corrected (thirteen).
> *Deliberately left for the team (unchanged):* §2.2 calendar dates, §9 team chart,
> §10 pitch-video link, and the citation-style normalisation in §12.

---

## Abstract

GTM Agent is a go-to-market (GTM) lead-generation pipeline for the EU
construction-technology sector. It continuously ingests public procurement
notices from *Tenders Electronic Daily* (TED), the EU's official procurement
journal, enriches them with downloaded dossier text, and matches each live
tender against a pool of ~15,000 candidate supplier companies derived from two
years of historical contract-award data. Matching uses a hybrid scoring model
that combines open-source multilingual sentence embeddings, deterministic
business rules (budget, geography, qualification), and a trained logistic
regression that fuses these signals into a calibrated win-probability. The system
then drafts evidence-grounded outreach emails for both sides of a deal — supplier
prospecting and a buyer-facing recommendation digest — using Claude, and captures
thumbs-up/down feedback that retrains the matcher's weights. A Claude tool-use
agent orchestrates the full workflow on demand. This report documents the
project's vision, timeline, architecture, methods (including prompt-engineering
strategy), team structure, current progress, and novelty.

---

## 1. Overall Project Vision

### 1.1 Problem

B2B sales teams in the construction and infrastructure sector spend a large share
of their time on **lead discovery**: finding live public tenders relevant to their
capabilities, and identifying which companies are credible bidders worth
partnering with or selling to. TED publishes tens of thousands of notices per
week across all sectors and 24 official languages, but it deliberately does **not**
publish the current bidders for an active tender (that information is confidential
during the bidding phase). Off-the-shelf tools either ignore historical award data
or hide it behind expensive third-party feeds.

### 1.2 Solution and scope

GTM Agent narrows TED to a configurable set of sectors via Common Procurement
Vocabulary (CPV) codes (construction CPV `45000000` and IT/services CPV
`72000000` for the MVP), and turns the public TED data stream into actionable
sales leads. The defining design choice is a **dual-stream strategy**: live
*Contract Notices* identify the opportunity; historical *Contract Award Notices*
supply the candidate companies (a firm that has repeatedly won similar tenders is
a strong candidate to bid again). The two streams are joined on CPV, buyer, and
budget band, recovering bidder signal that is otherwise unavailable for free.

**Key deliverables (in scope):**

- Automated ingestion of TED contract notices and award notices, plus dossier-PDF
  download where the document is directly reachable.
- Entity resolution of award winners into canonical company records.
- A hybrid tender↔company matcher with explainable sub-scores.
- Evidence-grounded, two-sided email generation (supplier + buyer).
- A feedback capture and weight-retraining loop.
- A Claude tool-use agent that plans and executes the pipeline from a natural-
  language goal.
- A Vue web dashboard and a documented REST API.

**Boundaries (explicitly out of scope for the MVP):**

- No credential-juggling scraping of authenticated buyer portals — restricted
  dossiers are flagged for manual review rather than scraped (see the Safety
  report).
- No translation layer — multilingual content is handled natively by a
  multilingual embedding model rather than machine translation.
- No authentication / multi-tenancy in Phase 1.
- No automatic sending of emails — drafts are produced for human review only.
- Vision-LLM blueprint parsing and a Neo4j incumbency knowledge graph are
  catalogued as **Future Work**, not committed to the MVP.

### 1.3 Success criteria (KPIs)

The matcher is evaluated by *backtesting*: reconstructing the world as of a past
tender's publication date, running the matcher, and recording where the actual
winner ranks. Target hit-rates across phases were Top-10 ≥ 50% (MVP) → ≥ 65%
(post-mid-term) → ≥ 75% (final). The final trained model (retrained 2026-07-05 on
80% of the award history, 16,812 awards) reports honest hit-rates on a 500-award
held-out backtest of **Hit@1 44.2% · Hit@3 54.0% · Hit@5 57.6%** (winner-in-pool),
so the Top-1 (≥ 25%) and Top-5 (≥ 55%) targets are met while the aspirational
Top-10 ≥ 75% is not separately measured — the current backtest reports up to Hit@5.
Full numbers are in §7. `[NEEDS INPUT: if a Top-10 / MRR figure is wanted for the
table, extend the backtest eval and paste it here.]`

---

## 2. Project Timeline

The project is organised into eleven phases over twelve teaching weeks, clustered
into five workstream categories: **Ingestion**, **Understanding & Matching**,
**Generation & Agent**, **Frontend & Demo**, and **Documentation & Evaluation**.

### 2.1 Gantt chart (stand-alone)

> **Legend:** ■ = active workstream · ⭐ = milestone. Weeks are teaching weeks;
> calendar anchors are in §2.2. This chart is intended to be read on its own.

| Workstream (category) | W1 | W2 | W3 | W4 | W5 | W6 | W7 | W8 | W9 | W10 | W11 | W12 |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **Ingestion** — bootstrap & architecture | ■ |  |  |  |  |  |  |  |  |  |  |  |
| **Ingestion** — TED contract + award notices | ■ | ■ | ■ |  |  |  |  |  |  |  |  |  |
| **Understanding** — tender structuring | | ■ | ■ | ■ |  |  |  |  |  |  |  |  |
| **Matching** — matcher MVP | | | | ■ | ■ |  |  |  |  |  |  |  |
| **Frontend** — dashboard | | | | | ■ | ■ | ■ | ■ |  |  |  |  |
| **Demo** — mid-term prep | | | | | ■ | ⭐ |  |  |  |  |  |  |
| **Matching** — embedding + LR weights | | | | | | ■ | ■ | ■ | ■ |  |  |  |
| **Generation** — email + evidence layer | | | | | | | ■ | ■ |  |  |  |  |
| **Generation** — feedback loop | | | | | | | | ■ | ■ |  |  |  |
| **Evaluation** — UAT | | | | | | | | | ■ | ■ |  |  |
| **Demo** — polish + pitch video | | | | | | | | | | ■ | ■ |  |
| **Documentation** — four deliverables | | | | | | | | | | | ■ | ■ |
| **Demo** — final presentation | | | | | | | | | | | | ⭐ |

### 2.2 Milestones and responsibilities

| # | Milestone | Target | Owner role | Done when |
|---|---|---|---|---|
| M1 | Repo + CI green | W1 | Project Lead | `docker compose up` runs; CI passes |
| M2 | TED ingestion end-to-end | W3 | Ingestion Lead | ≥ 200 notices + ≥ 5,000 awards stored *(achieved: ~21k awards / ~15k companies)* |
| M3 | Structured tender records | W4 | LLM/Extraction Lead | ≥ 90% schema-valid on a 50-notice sample `[NEEDS INPUT: understanding layer is still a stub — see §6]` |
| M4 | Matcher MVP | W5 | Matcher/ML Lead | Backtest winner-in-top-10 ≥ 50% |
| M5 | ⭐ Mid-term presentation | W6 (wk of 1 Jun) | Project Lead | Demo delivered |
| M6 | Embedding + trained weights | W9 | Matcher/ML Lead | LR win-probability live |
| M7 | Email + evidence layer | W8 | LLM/Extraction Lead | Every email claim traces to evidence |
| M8 | Feedback → weight retraining | W9 | Matcher/ML Lead | Retrain endpoint learns the signal |
| M9 | UAT complete | W10 | UAT/Docs Lead | ≥ 5 users; data analysed `[NEEDS INPUT]` |
| M10 | Pitch video recorded | W11 | Project Lead | Video + script delivered `[NEEDS INPUT]` |
| M11 | Docs within page limits | W11 | UAT/Docs Lead | Four docs peer-reviewed |
| M12 | ⭐ Final presentation + submission | W12 | Project Lead | Delivered + submitted |

> `[NEEDS INPUT: insert the real calendar dates for each teaching week (W1…W12)
> and confirm the mid-term/final presentation dates published on Moodle.]`
> `[TEAM DECISION: a polished graphical Gantt (e.g. via Mermaid, GanttProject, or
> Excel) is recommended for the final PDF — the rubric values a stand-alone
> visual. Decide who owns producing it from this table.]`

---

## 3. System Architecture

GTM Agent is a conventional three-tier application — a Python/FastAPI backend, a
PostgreSQL (with pgvector) database, and a Vue 3 frontend — composed of seven
logical sub-systems.

### 3.1 Component overview

```
                         ┌──────────────────────────────────────────┐
   TED v3 Search API ───►│  INGESTION                               │
   (contract + award     │  ted_client · awards_client ·            │
    notices, dossiers)   │  dossier_downloader · entity_resolution  │
                         └───────────────┬──────────────────────────┘
                                         │ writes
                         ┌───────────────▼──────────────────────────┐
                         │  POSTGRES 16 + pgvector                   │
                         │  tenders · awards · companies · documents │
                         │  company_profiles(embedding) · matches ·  │
                         │  emails · feedback · agent_runs · …       │
                         └───────────────┬──────────────────────────┘
        ┌────────────────────────────────┼─────────────────────────────┐
        ▼                                 ▼                             ▼
┌───────────────┐              ┌────────────────────┐        ┌──────────────────┐
│ MATCHING      │              │ GENERATION         │        │ AGENT            │
│ profile_build │              │ EvidenceExtractor  │        │ controller       │
│ embedder      │   matches    │ EmailDrafter(Claude)│       │ (planner-        │
│ semantic+rules│─────────────►│ EmailValidator     │        │  executor loop)  │
│ LR (features) │              │ supplier + buyer   │        │ 8 tools (SSE)    │
└───────────────┘              └────────────────────┘        └──────────────────┘
        ▲                                 │                             │
        │ feedback retrains weights       │ drafts                      │ orchestrates
        └─────────────── FEEDBACK ◄───────┴── REST API (FastAPI) ◄──────┘
                                          ▲
                                   Vue 3 dashboard
```

### 3.2 Sub-systems

1. **Ingestion** (`app/ingestion/`). A TED v3 Search API client with primary/
   secondary endpoints, transport-error retry, per-host 429 backoff, and
   `truststore`-based TLS (to survive corporate AV/proxy interception). Contract
   notices and award notices are upserted into Postgres using a `ON CONFLICT …
   RETURNING (xmax = 0)` trick to distinguish inserts from updates. Dossier PDFs
   are downloaded, validated by magic-bytes, SHA-256-deduplicated, and text is
   extracted with PyMuPDF. A CLI (`python -m app.ingestion`) exposes all jobs.

2. **Entity resolution** (`entity_resolution.py`). Award-winner names are
   normalised (lower-casing, punctuation stripping, legal-suffix removal) and
   resolved identifier-first (tax ID where present, else canonical name) into a
   `companies` table, with a `clean_identifier()` guard against junk IDs that
   would otherwise false-merge distinct firms.

3. **Understanding** (`app/understanding/`). A Claude `FieldExtractor` + validator
   turns a notice + dossier into a strict structured `TenderProfile`, persisted to
   `tenders.tender_profile` (JSONB). It is an explicit opt-in step
   (`POST /tenders/{id}/extract` or the agent's `extract_tender_profile` tool) rather
   than something run inside every match, keeping the matcher cheap and deterministic.
   The trusted TED columns are treated as authoritative; the LLM only enriches the
   soft fields (summary, required certifications/capabilities, keywords, language),
   and the extracted certifications feed the matcher's certification-disqualifier gate.

4. **Matching** (`app/matching/`). A two-layer pipeline. *Layer 1*
   (`profile_builder`) derives a `company_profiles` row (capability text +
   384-dimensional embedding + deal-size band + region) from each award winner's
   history. *Layer 2* (`pipeline.MatchingPipeline`) hard-filters ~15k candidates
   down to ≤ 200, computes ten features, and scores each with a trained logistic
   regression to produce a calibrated win-probability with per-feature
   explanations. The embedder and weights are injectable, so unit tests run
   without downloading model weights.

5. **Generation** (`app/generation/` + `api/v1/emails.py`). Two recipient types
   share one `emails` table: per-match **supplier** outreach and a per-tender
   **buyer** digest. `EvidenceExtractor` assembles a structured evidence dictionary
   (only verifiable facts: TED IDs, CPV codes, deadlines, scores); `EmailDrafter`
   prompts Claude under an evidence constraint with a deterministic template
   fallback; `EmailValidator` rejects any draft introducing unsupported claims.

6. **Agent** (`app/agent/`). A native Anthropic tool-use planner-executor loop
   (max 20 turns) that is **DB-first, streaming, and resumable** (see §3.4). It
   resolves a tender locally, runs the deterministic matcher, and narrates the
   result; the LLM only chooses tools and explains scores — it never ranks. Runs
   stream as Server-Sent Events and persist to `agent_sessions` (resumable) and
   `agent_runs` (audit); a `Reflector` summarises recent runs and feedback.

7. **API + frontend.** Seven FastAPI v1 routers (tenders, awards, companies,
   matches, emails, feedback, agent) with auto-generated OpenAPI docs; a Vue 3 +
   TypeScript + Pinia + Tailwind dashboard wired to them with a sample-data
   fallback.

### 3.3 Data model (selected)

Thirteen tables in a single PostgreSQL schema. The hot path uses pgvector: a
384-dimensional embedding column on `company_profiles` for fast cosine
similarity, with a generic 768-dimensional `embeddings` table reserved for
cross-model storage. Award winners (`companies`) and capability profiles
(`company_profiles`) are kept as two tables by design — different lifecycles and
key types. Full schema documentation is in `docs/Database_Explanation.md`.

### 3.4 Agent mode (DB-first orchestration)

The agent is the system's natural-language front door: a user states a goal
(*"find the top 3 suppliers for the Ilmenau school tender and explain why"*) and the
agent drives the pipeline. Its design follows three rules learned from a live demo
that the earlier version failed:

- **DB-first, not source-first.** The data is already ingested, so the agent
  *resolves* the named tender against the local database (`find_tender` — accepts the
  internal id, the public TED notice id, or title text) rather than fetching from TED.
  A partial name that matches several tenders triggers `ask_user`, which **pauses** the
  run for the user to pick; the conversation is persisted (`agent_sessions`) and
  resumed on their choice.
- **The LLM orchestrates; classical ML ranks.** `find_matches` runs the trained
  logistic-regression pipeline (§4.2); the LLM only selects the tool and explains the
  returned scores. It cannot introduce a company that isn't in the pool.
- **Bounded and offline-by-default.** The two network tools (`ingest_tenders`,
  `ingest_awards`) are *caged*: in dry-run they make **no** network call, and live they
  are bounded and run at most once per goal. The destructive bulk dossier sweep was
  removed from the agent entirely. (See the Safety report §1.2 for the full guard set.)

The run streams live progress to the UI as Server-Sent Events, and the result offers
two one-click actions: **Save results** (persists the analysis to `tender_reports`)
and **Draft email** to any of the top-3 matches.

Alongside the agent, the same screen carries an **ops command console** for operators:
`/retrain` (feedback→LR retrain), `/reflect` (run a reflection cycle), and
`/schedule on|off|status` (toggle the in-process ingestion/reflection scheduler at
runtime, without a restart). These are single-user operator conveniences today;
gating them behind authentication is deferred to the (unstarted) auth phase.

---

## 4. Method

### 4.1 Methodological principles

Three principles, agreed early, shaped every technical decision:

1. **Prefer classical ML to an LLM call where one exists.** Ranking is done by
   embeddings + logistic regression, not by asking an LLM "which company fits
   best." This is both cheaper and the core of the novelty argument (§8).
2. **Prefer open-source, locally-run embedding models** — no per-query API cost
   for the most frequent operation in the pipeline.
3. **Constrain the LLM to extraction and drafting**, never to free-form ranking
   or to unverified factual claims.

### 4.2 Hybrid matching method

The matcher decomposes the problem into independent layers, each using the right
tool:

| Layer | Tool | Role |
|---|---|---|
| Field extraction | LLM (Claude) | Structures fields — does **not** rank |
| Semantic similarity | Open-source sentence embeddings | Cosine similarity, tender ↔ company capability text |
| Budget / location / qualification | Deterministic rules | Hard-criteria sub-scores |
| Weight fusion | Logistic regression | Learns how to combine the sub-scores into P(win) |

The **disqualifier** removes clearly-ineligible candidates before any scoring.
The **semantic** sub-score embeds the tender once and compares it against each
candidate's capability text (built from the company's past award titles and
descriptions). **Rule** sub-scores cover budget overlap (after FX normalisation to
EUR), geographic fit (NUTS/country), and **CPV-prefix** qualification (hierarchical
partial credit: an exact 8-digit CPV match scores 1.0, down to a shared 2-digit
division scoring ~0.3). The **logistic regression** (trained on historical award
notices, ground truth = "did this company actually win?") fuses ten features into
a calibrated win-probability, and its coefficients give a directly interpretable
per-feature explanation.

The **feedback loop** retrains the LR on thumbs-up/down pairs: a durable feature
snapshot is stored with each feedback row so re-matching never destroys training
data, and a retrained parameter file is preferred over the base model when present
(deleting it reverts).

### 4.3 Prompt engineering

GenAI is used in three places, each with a deliberate prompting strategy:

- **Structured field extraction (understanding layer).** A *Chain-of-Thought*
  (Wei et al., 2022) prompt asks the model to (1) state in one sentence what kind
  of section it is reading, (2) list candidate fields, and (3) emit a JSON
  fragment matching a strict schema. The scratchpad is discarded; only the JSON is
  parsed and validated, with shape-failures rejected. For long dossiers a
  *map-reduce* summarisation pattern is used to avoid the "lost-in-the-middle"
  degradation of long-context models (Liu et al., 2023). The model is prompted in
  English with foreign-language source text appended verbatim, exploiting the
  model's native multilingual reading rather than a translation step.

- **Evidence-grounded email drafting.** A two-step pattern: a deterministic
  extractor first builds the evidence list (TED ID, CPV codes, deadline, match
  scores, company facts), then the generator is prompted with **only** that
  evidence and instructed to introduce no claim outside it. The output is
  post-validated; any unsupported named entity or claim flags the draft for review
  rather than auto-sending. The prompt also instructs the model to match the
  tender's language automatically (verified live: a German tender produced a
  German email citing only real facts).

- **Agent orchestration.** A planner-executor system prompt defines the goal, the
  tool set (as JSON schemas), and the safety constraints (DB-first resolution,
  offline-by-default ingest, read-only SQL, `ask_user` for ambiguity). Tool
  definitions and the system prompt are stable across turns to benefit from prompt
  caching; the messages persist to `agent_sessions` so a paused run resumes exactly
  where it left off.

> `[TEAM DECISION: include 1–2 verbatim prompt excerpts (extraction + email) in
> an appendix? The rubric explicitly grades the prompt-engineering discussion.]`

### 4.4 Engineering process

Trunk-based development on `main` with feature branches and PR review; GitHub
Actions CI runs the backend test suite (~346 tests, kept torch-free via injected
fake embedders), frontend lint+build, and an Alembic migration smoke against a
real pgvector container. Schema changes ship as additive Alembic migrations
(`0001`→`0015`). A train/serve **feature-contract drift guard** keeps the offline
model trainer and the live matcher's feature math in lock-step (a CI-safe test
pins the served feature vector to the committed model parameters). A recurring
**find-a-gap → fix → verify** loop (documented in
`archive/internal-logs/Notes.md` and `archive/internal-logs/integration_gap_tracker.md`) drove iterative quality:
e.g. discovering via live smoke that `qualification` scored 0 for every match,
then fixing it with CPV-prefix partial credit and re-verifying that 89/100 top
matches then scored > 0.

---

## 5. Technology Used

| Layer | Technology | Notes |
|---|---|---|
| Language / runtime | Python 3.11 | Pinned for dependency compatibility |
| HTTP framework | FastAPI 0.115 | First-class Pydantic v2 + OpenAPI |
| Validation | Pydantic v2 | Strict schema enforcement |
| ORM / migrations | SQLAlchemy 2.0 / Alembic | Typed `Mapped[]` API |
| Database | PostgreSQL 16 + pgvector | Single schema; vector similarity in-DB |
| HTTP client | httpx (+ truststore) | `requests` banned by spec |
| PDF text | PyMuPDF | Dossier extraction |
| Embeddings | sentence-transformers — `paraphrase-multilingual-MiniLM-L12-v2` (384-d), CPU-only | Multilingual MiniLM; lazy-loaded |
| Classical ML | scikit-learn + joblib | Trained logistic-regression matcher (calibrated win-probability) |
| LLM | Anthropic Claude (`claude-sonnet-4-6`) | Agent, reflection, email drafting |
| Scheduler | APScheduler (in-process) | Opt-in cron loop (ingest + reflect); runtime on/off/status toggle |
| Frontend | Vue 3 / TypeScript / Vite 5 / Pinia / Tailwind | Three-column dashboard |
| CI | GitHub Actions | pytest · lint+build · migration smoke |
| Containerisation | Docker Compose | db + backend + frontend |

The ML stack lives in a separate `requirements-ml.txt` because `torch` is heavy;
the matcher lazy-imports it so the API boot, CI, and normal tests stay
torch-free.

---

## 6. Current Progress and Future Plans

### 6.1 Current progress (as of 2026-07-05)

| Component | Status |
|---|---|
| Repo scaffold, schema, CI | **Done** |
| TED contract-notice ingestion | **Done — live-verified** |
| Award back-fill + entity resolution | **Done — ~21k awards / ~15k companies (24 months)** |
| Dossier downloader + ingestion CLI | **Done — live-verified** |
| Understanding layer (Claude `FieldExtractor`) | **Done — `TenderProfile` persisted (G11)** |
| Matching (hybrid + trained LR mode) | **Done — live-smoked; unified v5 model serving** |
| Two-sided email generation (Claude) | **Done — evidence-grounded, live-verified** |
| Feedback capture + LR retraining | **Done** |
| Scheduler (APScheduler, opt-in) + reflection loop | **Done (G13/G9); runtime on/off/status toggle (G27)** |
| Agent (DB-first, streaming, resumable; result actions) | **Done — reworked G22/G28, live-smoked** |
| Ops command console (`/retrain`, `/reflect`, `/schedule`, `/help`) | **Done (G27)** |
| REST API (7 routers) + Vue dashboard (7 views) | **Done — with sample-data fallback** |
| ML training dataset export + retrain on 80% of awards | **Done (G23) — 16,812 training awards** |

The headline integration achievement was unifying two matchers — a simple
fixed-weight one in the app and a stronger but disconnected trained "v5" logistic
regression — into a single pipeline that serves the trained model behind the
existing API, agent, and frontend, with the feedback loop live and emails written
by Claude.

### 6.2 Known limitations and future plans

- **Web-scraped capability profiles** — profiles are derived from award history
  only (thin); per-portal dossier scraping is deferred behind an adapter-registry
  design. This fixed supplier pool is also *why* the certification disqualifier gate,
  though fully wired to the Understanding layer, stays inert in production (award data
  carries no supplier-certification field).
- **Auth / multi-tenancy** — Phase 5, not started.
- **Verified outreach contacts** — TED carries no supplier email, so supplier
  recipients are website-derived and flagged *unverified* rather than fabricated.
- **Backtest KPI numbers** — finalised from the 2026-07-05 retrain (§7); a Top-10
  / MRR figure would require extending the eval past Hit@5.

> *Resolved since the 2026-06-21 draft:* the APScheduler loop (G13), the Understanding
> layer + cert gate (G11/G12), reflection→behaviour wiring (G9), the awards/companies/
> agent UI + persisted weights (G15/G16), the agent rework + result actions (G22/G28),
> the ops command console + runtime scheduler toggle (G27), the train/serve drift guard
> (G20), and the 80%-data model retrain (G23) all shipped — see
> `archive/internal-logs/integration_gap_tracker.md`.
- **Future-work candidates** (catalogued, not committed): Vision-LLM blueprint
  parsing; Neo4j incumbency knowledge graph; embedding ensemble (adding
  `all-mpnet-base-v2` and `multilingual-e5-large`).

---

## 7. Evaluation

The numbers below are from a reproducible backtest of the final trained model
(retrained 2026-07-05 on 80% of the award history; 16,812 training awards, 500
held-out awards, winner guaranteed in the candidate pool). The backtest
reconstructs the world as of each held-out tender and records where the true
winner ranks. Source: `archive/data-exports/model_report.json`.

| Metric | MVP target | Final target | Achieved (2026-07-05) |
|---|:--:|:--:|:--:|
| Top-1 accuracy (Hit@1) | — | ≥ 25% | **44.2%** (221/500) ✔ |
| Top-3 accuracy (Hit@3) | — | — | **54.0%** (270/500) |
| Top-5 accuracy (Hit@5) | ≥ 30% | ≥ 55% | **57.6%** (288/500) ✔ |
| Top-10 accuracy | ≥ 50% | ≥ 75% | `[NEEDS INPUT: not measured — eval reports up to Hit@5; extend to Hit@10]` |
| Disqualifier false-positive rate | 0 | ≤ 1% | `[NEEDS INPUT: measure on the held-out set]` |

The Top-1 and Top-5 final targets are met; the aspirational Top-10 ≥ 75% was not
separately measured (the current eval stops at Hit@5). Relative to the previous
50%-data model the retrain is essentially flat (Hit@3 54.8% → 54.0% on a harder,
later held-out slice), and the model is structurally stable (same coefficient
signs; strongest positive features: 4-digit CPV match, exact NUTS region, semantic
similarity).

Qualitative live-smoke evidence is strong: on a Czech road-resurfacing tender the
top matches are genuine Czech road builders (EUROVIA, STRABAG, SWIETELSKY, PORR);
after enriching capability text, semantic cosines for relevant matches rose from
~0.24–0.43 to 0.67–0.82 and win-probabilities from ~0.27 to ~0.79. See
`archive/internal-logs/matching_pipeline_smoke_record.md`.

---

## 8. Novelty / Value Proposition

GTM Agent is **not** a wrapper around a GenAI API. Its contribution is a
*combination of methods* that differs from the industry baseline:

1. **Dual-stream TED design.** Recovering candidate-bidder signal for free by
   joining live contract notices with historical award notices on CPV/buyer/
   budget — solving the "TED gives the tender but not the bidders" problem that
   most tools either ignore or pay a vendor to solve.
2. **Hybrid, explainable matcher.** A decomposed pipeline (embeddings + rules +
   trained logistic regression) where the LLM only structures fields and never
   ranks. Every score is interpretable and traceable to its sub-scores.
3. **Evidence-grounded, two-sided generation.** A deterministic
   evidence-extraction step plus post-validation guarantees that every factual
   claim in an outreach email traces to a verifiable source — and the system
   serves *both* supplier outreach and a buyer recommendation digest, not just one
   direction.
4. **Closed feedback loop.** Thumbs-up/down retrains the matcher's fusion weights
   with durable training snapshots, so the system improves with use.

Relative to the rubric's Section 5, the hybrid matcher (point 2) is the single
largest novelty, reinforced by the dual stream (1) and the evidence-grounded
emails (3).

---

## 9. Team Chart

> `[NEEDS INPUT: replace the role-only template below with real names, and
> tailor the "Key contributions" column to what each member actually did. The
> plan assumed seven members each with one primary + one shared secondary role.]`

| Member | Primary role | Key contributions | Phases |
|---|---|---|---|
| `[NEEDS INPUT]` | Project Lead / Architect | Timeline, architecture, kick-off + rehearsals, key decisions | 0, 4, 9, 11 |
| `[NEEDS INPUT]` | Backend / Ingestion Lead | TED clients, awards back-fill, dossier downloader, FastAPI scaffold | 0–3, 5 |
| `[NEEDS INPUT]` | Matcher / ML Lead | Disqualifier, embeddings, rules, LR weight learner, explanations | 3, 5–7 |
| `[NEEDS INPUT]` | LLM / Extraction Lead | Prompt engineering, schema validation, evidence extractor; co-owns Safety report | 2, 6 |
| `[NEEDS INPUT]` | Database / Backend #2 | SQLAlchemy models, migrations, pgvector indexing | 0–2, 7 |
| `[NEEDS INPUT]` | Frontend Lead | Vue dashboard, weight sliders, evidence panel, email UI | 4, 6, 8 |
| `[NEEDS INPUT]` | UAT / Documentation Lead | UAT recruitment + execution; coordinates the four deliverable docs | 8, 10 |

> `[NEEDS INPUT: the project is led by Swaraj Shrestha. Confirm Swaraj's exact
> role title and add the remaining members. Note the original industry partner
> (ArctisAI) withdrew; the team delivered independently.]`

---

## 10. Pitch Video

A ~60-second professional product pitch is submitted as a separate attachment per
the rubric. Suggested structure (state the problem, then show the app solving it):

1. **Problem (10s)** — "Construction-tech sales teams drown in thousands of EU
   tenders and can't see who the credible bidders are."
2. **Solution + live demo (40s)** — pick a live tender → show the ranked supplier
   matches with explanations → nudge a weight → open a candidate's evidence panel
   → generate an evidence-grounded email, pointing out the GenAI tool calls and
   that every claim is sourced.
3. **Close (10s)** — feedback loop + two-sided value proposition.

> `[NEEDS INPUT: record the video (1080p, scripted voiceover, live software — not
> static slides). Owner + recording date TBD.]`

---

## 11. Acknowledgment of GenAI Usage

GenAI was used both *in the product* and *in producing this document*.

- **In the product:** Anthropic Claude (`claude-sonnet-4-6`) powers the
  orchestration agent, the reflection loop, and evidence-grounded email drafting;
  open-source sentence-transformer models provide embeddings. The development team
  also used Claude (via Claude Code) extensively as a coding and documentation
  assistant.
- **In this document:** A Claude-based assistant drafted this report's structure
  and prose from the team's own source materials (`README.md`, `docs/`,
  `CLAUDE.md`, and the code), and verified the academic citations in §12 against
  primary sources. All content was reviewed, corrected, and approved by the team;
  factual gaps are explicitly flagged for human completion. GenAI was used as an
  assistant, not as an unchecked author.

> `[NEEDS INPUT: confirm/adjust this acknowledgment to reflect exactly how the
> team used GenAI tools, per the rubric requirement.]`

---

## 12. References

1. Wang, W., Wei, F., Dong, L., Bao, H., Yang, N., & Zhou, M. (2020). *MiniLM:
   Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained
   Transformers.* Advances in Neural Information Processing Systems (NeurIPS) 33.
   arXiv:2002.10957. — *the model family behind the project's
   `paraphrase-multilingual-MiniLM-L12-v2` embedder.*
2. Reimers, N., & Gurevych, I. (2019). *Sentence-BERT: Sentence Embeddings using
   Siamese BERT-Networks.* Proceedings of EMNLP-IJCNLP 2019, 3982–3992.
   arXiv:1908.10084. — *the sentence-embedding method and `sentence-transformers`
   library used for semantic matching.*
3. Song, K., Tan, X., Qin, T., Lu, J., & Liu, T.-Y. (2020). *MPNet: Masked and
   Permuted Pre-training for Language Understanding.* NeurIPS 33.
   arXiv:2004.09297. — *basis of the `all-mpnet-base-v2` ensemble candidate
   (future work).*
4. Wang, L., Yang, N., Huang, X., Yang, L., Majumder, R., & Wei, F. (2024).
   *Multilingual E5 Text Embeddings: A Technical Report.* arXiv:2402.05672. —
   *`multilingual-e5-large`, the multilingual ensemble candidate (future work).*
5. Wei, J., Wang, X., Schuurmans, D., Bosma, M., Ichter, B., Xia, F., Chi, E., Le,
   Q., & Zhou, D. (2022). *Chain-of-Thought Prompting Elicits Reasoning in Large
   Language Models.* NeurIPS 35. arXiv:2201.11903. — *the extraction prompt
   strategy.*
6. Liu, N. F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F., &
   Liang, P. (2023). *Lost in the Middle: How Language Models Use Long Contexts.*
   Transactions of the ACL (TACL). arXiv:2307.03172. — *motivation for the
   map-reduce dossier summarisation.*
7. pgvector contributors. *pgvector: Open-source vector similarity search for
   PostgreSQL.* https://github.com/pgvector/pgvector
8. Anthropic. *Claude (Sonnet) model family and API documentation.*
   https://docs.claude.com
9. Publications Office of the European Union. *Tenders Electronic Daily (TED) —
   Search API v3.* https://ted.europa.eu
10. European Commission. *Common Procurement Vocabulary (CPV)* — Regulation (EC)
    No 2195/2002; *eForms* — Commission Implementing Regulation (EU) 2019/1780.

> `[NEEDS INPUT: choose one citation style (e.g. IEEE or APA) and normalise all
> entries to it; add any further sources the team relied on.]`
