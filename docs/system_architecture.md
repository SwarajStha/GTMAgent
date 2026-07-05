# GTM Agent — System Architecture (for revising the Architecture & Process Flow diagram)

> **Purpose of this file.** This describes the **current, true** system architecture of
> GTMAgent, structured to match the swim-lane layout of the existing
> `Architecture & Process Flow` slide (lanes: **Frontend / Backend / Database /
> External**; phases across the top). Use it to **update** that diagram so it reflects
> what is actually built. Source: `docs/architecture.md` + the live code. A dedicated
> **§7 "What to change vs the current diagram"** lists the concrete edits.

---

## 1. The pipeline in one line

Ingest EU TED tenders → understand each tender (LLM field extraction) → match it against
a supplier pool derived from past award winners (multilingual embeddings + rules +
a trained model) → generate evidence-grounded outreach emails → capture thumbs-up/down
feedback that retrains the model. An LLM **agent** orchestrates the match-and-explain
step and answers analytical questions.

---

## 2. Swim lanes and phases (map to the diagram)

Keep the four horizontal lanes and the phase columns. Corrected phase headers:

| Phase column | Header to show | Status |
|---|---|---|
| Phase 1 | **Data Ingestion** | ✅ live |
| Phase 2 | **Tender Understanding** | ✅ live |
| Phase 3 | **Agentic Matching (core)** | ✅ live |
| Phases 4–5 | **Dashboard & Email Generation + Feedback** | ✅ live |

---

## 3. Phase-by-phase content (corrected to reality)

### Phase 1 — Data Ingestion (Backend + External + Database)
- **Poll TED contract notices** (CPV-filtered) from the live TED API v3 → `tenders`.
- **Poll TED award history** (24-month back-fill, ~21k awards / ~15k companies) →
  `awards` + `companies`. This is the raw material for the supplier pool.
- **Download dossier PDFs** — exists as an ingestion utility (portal PDFs; 401/403 →
  flagged restricted). Keep it, but show it as **greyed / limited** — most buyer portals
  return HTML, so coverage is thin, and it is **not** part of the agent's toolset.
- **Scheduler:** an in-process APScheduler (opt-in) runs contracts / dossiers / awards /
  reflection on cron. The `python -m app.ingestion` CLI serves one-shot runs.
- **DB tables:** `tenders`, `awards`, `companies`, `documents`.
- **External:** TED API (`api.ted.europa.eu/v3`) — contract notices + award history.

### Phase 2 — Tender Understanding (Backend + Database)
- **LLM field extraction** (`FieldExtractor`, Claude): enriches **only the soft fields**
  a tender's structured columns can't give — summary, required certifications, required
  capabilities, keywords, language. The trusted TED columns (CPV, title, budget,
  country, deadline) are **authoritative and never overwritten**.
- **Schema validation** (`ExtractionValidator`): repairs CPV codes, drops junk budgets,
  flags past deadlines, dedupes lists.
- Result persists to **`tenders.tender_profile`** (JSONB). This is an **explicit opt-in
  step**, not run automatically inside matching (keeps matching cheap and deterministic).
- **DB:** `tenders` (enriched with the structured profile).

### Phase 3 — Agentic Matching (core) (Backend + Database)
This is the corrected heart of the diagram. The real matching pipeline:
- **Supplier-pool builder (Layer 1):** derives a `company_profiles` row from each past
  award winner (capability text from award titles/descriptions + CPV + regions; deal-size
  from past contract values; a multilingual embedding). Idempotent.
- **Matcher (Layer 2), `MatchingPipeline.run(tender_id)`:**
  1. **Hard filter** narrows the ~15k pool to ≤200 candidates (CPV / region gates, plus
     an optional certification gate driven by Phase 2's extracted certifications).
  2. **Score candidates** — the default path scores each candidate with a **trained
     logistic-regression model over 10 features** (`predict_proba` → a calibrated
     win-probability). A legacy fixed-weight blend (semantic 0.40 / budget 0.20 /
     location 0.20 / qualification 0.20) remains as a fallback and as the operator
     "adjust weights & re-rank" lever.
  3. **Rank & explain** — produces per-supplier sub-scores + an explanation; writes the
     `matches` rows (idempotently).
- **Embeddings:** `paraphrase-multilingual-MiniLM-L12-v2` (384-d, multilingual — the TED
  corpus spans 24 languages), CPU-only, lazy-loaded.
- **The agent** (see §4) orchestrates this step and narrates the result; it does **not**
  compute scores.
- **DB:** `company_profiles` (the matchable supplier pool, with embeddings), `matches`
  (scores + explanations).

### Phases 4–5 — Dashboard, Email Generation, Feedback (Frontend + Backend + Database)
- **Frontend dashboard:** review ranked leads, adjust match weights (server-side
  re-rank), 1-click actions. Seven screens (Tenders / Matches / Emails / Awards /
  Companies / Agent / Home).
- **Two-sided email generation** (Claude, evidence-grounded, deterministic fallback):
  - **supplier** — per-match outreach to a matched company.
  - **buyer** — per-tender digest to the tender issuer recommending the ranked suppliers.
  `EvidenceExtractor` gathers verifiable facts → `EmailDrafter` writes under an evidence
  constraint → `EmailValidator` is a structural guardrail. Drafts persist to `emails`.
- **Feedback loop:** thumbs up/down on a match is captured in `feedback` and **retrains
  the logistic-regression weights** (a reflection cycle runs this and writes
  `reflections`).
- **DB:** `emails`, `feedback`, `reflections`, `tender_reports` (saved agent analyses).

---

## 4. The Agent (Phase 3 overlay — the big correction)

The agent was **reworked** into a **DB-first, streaming, resumable** loop. It resolves a
tender locally, runs the deterministic matcher, and explains — it never reaches the
internet on the normal path. Full detail is in
[`agentic_behavior_description.md`](agentic_behavior_description.md); the diagram-level
summary:

- **Tools (8):** `find_tender`, `find_matches`, `extract_tender_profile`, `draft_email`,
  `query_db` (read-only analytics), `ask_user` (human-in-the-loop pause), and the two
  **caged** live fallbacks `ingest_tenders` / `ingest_awards`.
- **No web search. No company-website scraping.** These were concept-only and were never
  built — remove them from the agent depiction.
- **Streaming + resumable:** live progress via Server-Sent Events; `ask_user` pauses and
  the conversation is saved to `agent_sessions`, then resumed on the user's choice.
- **Caged network:** in offline/dry-run mode the ingest tools make **no** network call;
  live ingest is bounded and at-most-once-per-run.
- **Post-run actions:** Save results → `tender_reports`; Draft email via a 🥇/🥈/🥉
  selector.

---

## 5. Database tables (cylinders in the DATABASE lane)

`tenders` · `awards` · `companies` · `documents` · `company_profiles` · `matches` ·
`emails` · `feedback` · `reflections` · `agent_sessions` · `agent_runs` ·
`tender_reports`. (Migration head `0015`.)

---

## 6. External systems (EXTERNAL lane)

- **TED API** (`api.ted.europa.eu/v3`) — the **only** external data source: contract
  notices (Phase 1) + award history + the two caged agent fallbacks.
- **Anthropic Claude API** — the LLM used for field extraction, agent orchestration,
  email drafting, and reflection narratives. Every LLM path is offline-safe (deterministic
  fallback when no API key). *(Add this box — the current diagram omits it.)*
- **~~Web Search API~~ / ~~Company-website scraper~~ — REMOVE.** Not built; not on the
  roadmap for the agent.

---

## 7. What to change vs the current diagram (the edit list)

Apply these edits to the attached `Architecture & Process Flow` slide:

1. **Phase 2 header** — keep "Tender Understanding". It is now **live** (was drawn as a
   future/blue box); the LLM field extractor + schema validator are implemented and
   persist to `tenders.tender_profile`.
2. **Remove the "Web search fallback" agent box** (Phase 3) — never built.
3. **Remove the "Scrape company websites … [idea phase]" agent box** (Phase 3) — never
   built.
4. **Remove the External "Web Search API" and "Company websites (agent scraper)" boxes.**
5. **Replace the "Query past award winners for backfill → Enough candidates? → …" agent
   sub-flow** with the real agent flow: `find_tender` → (optional) `extract_tender_profile`
   → `find_matches` (deterministic pipeline) → explain. Keep a single **"zero matches?"**
   decision that leads to the *caged* `ingest_awards` fallback (dashed).
6. **Relabel "Score candidates: SBERT · rules · past-win bonus"** →
   **"Score candidates: multilingual embeddings (MiniLM) · rules · trained model
   (logistic regression, calibrated win-probability)."**
7. **Add a `query_db` (read-only analytics) branch** off the agent — the agent can now
   answer aggregation/ranking questions, not only match a single tender.
8. **Add an `ask_user` pause/resume loop** back to the Frontend lane (human-in-the-loop
   disambiguation).
9. **Add the Anthropic Claude API** box to the EXTERNAL lane (LLM for extraction,
   agent, email, reflection).
10. **Grey / shrink "Download dossier PDFs"** and drop it from any agent path — it's an
    ingestion-only utility, not an agent capability.
11. **Add new DB cylinders:** `company_profiles`, `reflections`, `agent_sessions`,
    `tender_reports` (alongside the existing tenders/awards/companies/documents/matches/
    emails/feedback).
12. **Add a small "Feedback → retrain model" arrow** from the `feedback` table back to
    the Phase-3 scoring step (the learning loop).
13. **Add a safety caption** near the agent's external fallbacks:
    *"Offline mode = no network; live ingest is caged, bounded, once-per-run."*

Keep the legend, the TUM branding, the "Group 2" / course footer, and the overall
swim-lane look — this is a **revision**, not a redraw.
