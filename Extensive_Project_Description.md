# Extensive Project Description — GTM Agent
### Companion Document to Project Proposal v2

**Technical University of Munich (TUM)**  
School of Computation, Information and Technology  
Foundations and Applications of Generative AI (CITHN2014)

---

> **Topic:** Project 4 — GTM Agent  
> **Partner:** None *(ArctisAI has withdrawn; the team is continuing the project independently)*

---

## Document Conventions

| Marker | Meaning |
|--------|---------|
| 🔴 **[Claude suggestion]** | A recommendation from Claude not directly grounded in the team's source materials. Each can be accepted, adapted, or rejected. |

> **About this document.** This document is an extension of — not a replacement for — the Project Proposal v2. Anywhere we make a design choice that is not directly grounded in the original project brief, the proposal v2, the team's submitted ideas, or the GenAI course grading rubric, we mark it explicitly as a Claude suggestion using the red sidebar shown above, so that the team can decide whether to accept, reject, or adapt it.

---

## Table of Contents

1. [Project Recap & Strategic Context](#1-project-recap--strategic-context)
2. [Data Acquisition Layer](#2-data-acquisition-layer)
3. [Tender Understanding & Section Identification](#3-tender-understanding--section-identification)
4. [Hybrid Matching Algorithm — The Core Novelty](#4-hybrid-matching-algorithm--the-core-novelty)
5. [Company Discovery](#5-company-discovery)
6. [Database Architecture](#6-database-architecture)
7. [Evidence-Grounded Email Generation](#7-evidence-grounded-email-generation)
8. [Frontend Dashboard](#8-frontend-dashboard)
9. [Mapping to Grading Criteria](#9-mapping-to-grading-criteria)
10. [Open Questions / Suggestions for the Team](#10-open-questions--suggestions-for-the-team)

---

## 1. Project Recap & Strategic Context

Project 4 in the TUM GenAI 2026 catalogue, GTM Agent, was originally proposed with industry partner ArctisAI. The brief calls for a pipeline that monitors EU tender portals, identifies owners of active projects, scrapes candidate-bidder companies, and generates highly personalised, context-aware business-development emails, all backed by a database of leads. ArctisAI has since withdrawn, so the team is delivering the project independently. The strategic intent is unchanged: build something a real construction-tech sales team could put in front of a customer, not a thin LLM wrapper.

Three constraints from the team's most recent feedback shape the rest of this document:

1. Where a classical machine-learning solution exists, **prefer it over an LLM call**.
2. Prefer **open-source embeddings** and models.
3. Focus on Section 5 of the grading rubric (**"Novelty / Value Proposition"**), which awards no points for simple wrappers of GenAI APIs and explicitly rewards a new approach, workflow, or combination of methods compared to industry baseline.

Every architectural decision below is justified against at least one of these three constraints.

---

### 1.1 Industry Scope via CPV Codes

TED publishes tens of thousands of notices per week across every conceivable sector. Trying to match against "all of TED" dilutes both the matching signal and our ability to evaluate the system. Per the v2 proposal, we restrict the agent to 2–3 sectors using **Common Procurement Vocabulary (CPV) codes** — the standardised EU classification that every TED notice already carries.

> 🔴 **[Claude suggestion]** Concretely, we recommend:
> - **Construction** — CPV `45000000-7`
> - **Renewable Energy / Solar & Wind** — CPV `09330000-1`, `31121340-5`
> - **IT Services & Cybersecurity** — CPV `72000000-5`, `72500000-0`
>
> These three give us heterogeneity across very different bidder profiles (physical contractors vs. SaaS/IT firms vs. energy specialists), which is good both for demonstrating that the matcher generalises and for stress-testing the dossier-PDF pipeline (construction tenders are very PDF-heavy; IT tenders are much more text-only).

The CPV filter is configurable from the dashboard, so the team can extend the scope later without touching the matcher.

---

## 2. Data Acquisition Layer

### 2.1 The TED Dual-Stream Strategy

The TED Search API v2 exposes two complementary classes of notice. Both are returned as JSON. The team's plan, captured in the v2 proposal, is to use them in a deliberately asymmetric way:

| Stream | Role in the Pipeline |
|--------|---------------------|
| **Contract Notices** (Active Tenders) | These are the live opportunities. We use them to identify the tender to bid on, extract its requirements, and follow links to the dossier PDFs. We do NOT get the list of current applicants — that is confidential during the bidding phase. |
| **Contract Award Notices** (Past Results) | These publish, after the fact, who won what. We use them as the primary candidate source for "close bidders" — if Company X has won three previous tenders very similar to the current active one, X is a strong candidate to bid again. Award notices also give us per-company win history, used as a learned feature in the matcher (see §4). |
| **Wider web search** (fallback) | Used only when historical award data for a given CPV is sparse, or when we want to broaden beyond previous winners. Scope-limited and rate-limited so that web scraping does not dominate the pipeline. |

This dual-stream design is the answer to a real engineering problem: **TED gives us the tender but not the bidders.** Most off-the-shelf tools either ignore award history entirely, or require a paid third-party feed. We get equivalent signal for free by joining active and past notices on CPV, buyer (contracting authority), and budget band.

---

### 2.2 Contract Notice Ingestion

A scheduled worker polls the TED Search API v2 with a CPV-code filter and a recency window. Each notice is normalised, persisted to the `tenders` table (§6.2), and pushed onto an internal queue for downstream processing. Polling cadence is configurable; we expect once-daily polling to be sufficient for an MVP, but the architecture supports sub-hourly without changes.

> 🔴 **[Claude suggestion]** Use a simple FastAPI worker with APScheduler for the cron, and Redis as the queue. This avoids dragging in Airflow or Celery for an MVP — they are an order of magnitude more complex to set up and the team has only a semester. The pipeline is easy to swap to a heavier orchestrator later if the supervisor wants it.

---

### 2.3 Contract Award Notice Ingestion

Award notices are pulled in a separate, lower-frequency job. For each award we extract the buyer, the CPV code, the winning bidder name, the final contract value, and the number of offers received. Two technical issues need engineering attention:

- **Entity resolution.** The same company appears under slightly different legal names in different notices ("Hochtief AG" vs. "Hochtief Aktiengesellschaft" vs. local subsidiaries). We resolve these to a canonical company ID using fuzzy string matching plus an LLM tie-breaker on ambiguous cases.
- **Schema drift.** TED has migrated from legacy XML to eForms, and historical bulk downloads use multiple schema versions. The ingestion layer normalises everything into one internal schema.

---

### 2.4 Identifying Main Sections of the Tender

A required addition for v2 is identifying the main sections of each tender notice. Notices are semi-structured: TED gives us metadata fields, but the substantive technical specification is usually only in the dossier PDF. Our agent extracts a fixed structured view from the union of the JSON and the PDF:

| Field | Source / Extraction Approach |
|-------|------------------------------|
| `title`, `buyer`, `CPV codes`, `country` | TED JSON metadata — no LLM needed |
| `deadline`, `estimated_budget`, `currency` | TED JSON metadata when present; LLM regex-style extraction over the PDF cover page when not |
| `technical_requirements` | LLM extraction over the dossier with a Chain-of-Thought prompt. Output is a list of atomic requirements with a category tag |
| `eligibility` (size, certifications, geography) | LLM extraction restricted to the eligibility chapter of the dossier |
| `evaluation_criteria` & weights | LLM extraction; values are normalised to percentages summing to 100 so the matcher can use them as weight priors |
| `attached_documents` | Crawler follows hyperlinks inside the PDF (PyMuPDF) and inside the JSON `document_url` field |

---

### 2.5 Following Links to Larger Tender PDFs

TED Contract Notices typically reference one or more dossier PDFs ("procurement documents"), sometimes hosted on the buyer's own portal behind a registration wall. Our crawler pulls the immediate `document_url` field and additionally extracts hyperlinks from the notice text and from any already-downloaded PDFs (using PyMuPDF link extraction).

> 🔴 **[Claude suggestion]** For dossiers behind authentication, we recommend **NOT** building a credential-juggling scraper for the MVP — it is fragile and ethically grey. Instead, mark such tenders as `"restricted"` in the database and surface them in the dashboard with a one-click "open in browser" action so the human user pulls the dossier manually. This is honest about the constraint and consistent with the GenAI Safety report (Document 4 in the rubric).

---

### 2.6 Map-Reduce Summarisation for Long Dossiers

Dossier PDFs of 50–200 pages exceed comfortable LLM context, and even when they fit, they suffer from the well-known **"lost-in-the-middle" problem**. We split each dossier into semantic chunks (by heading, falling back to fixed-size with overlap), summarise each chunk into a structured-fields contribution, and then reduce all chunks into a single tender record:

- Chunks tagged as `"technical requirement"` → contribute to the requirements list
- Chunks tagged as `"eligibility"` → contribute to the eligibility filter
- All other chunks → contribute to metadata and summary fields

---

## 3. Tender Understanding & Section Identification

Section 2 covered how the tender content is fetched. Section 3 is about turning that content into machine-readable structure. This is an LLM-heavy step — because legal and technical prose is exactly what LLMs are good at — but every output is constrained by a strict JSON schema, validated, and rejected on shape failure. **There is no free-form ranking happening here; the LLM's only job is feature extraction.**

---

### 3.1 Output Schema (v0)

```json
{
  "id": "string",
  "source_notice_id": "string",
  "cpv_codes": ["string"],
  "buyer": {
    "id": "string",
    "name": "string",
    "country": "string",
    "nuts_region": "string"
  },
  "deadline": "ISO date",
  "budget": {
    "amount": "number",
    "currency": "string",
    "is_estimate": "boolean"
  },
  "geographic_scope": ["string"],
  "technical_requirements": [
    {
      "id": "string",
      "category": "string",
      "text": "string",
      "evidence_span": {
        "doc_id": "string",
        "page": "number",
        "chars": [0, 0]
      }
    }
  ],
  "eligibility": {
    "min_company_size": "int (optional)",
    "required_certifications": ["string"],
    "geographic_restrictions": ["string"],
    "other": ["string"]
  },
  "evaluation_criteria": [
    { "name": "string", "weight_percent": "number" }
  ],
  "attached_documents": [
    { "url": "string", "status": "string", "hash": "string" }
  ],
  "language": "ISO code",
  "ingested_at": "timestamp"
}
```

Every requirement and eligibility item carries an `evidence_span` — the exact (document, page, character range) it was extracted from. This is what makes evidence-grounded email generation later (§7) possible without hallucination.

---

### 3.2 Chain-of-Thought Prompt Design

For each chunk, the prompt asks the model to:

1. State in one sentence what kind of section this is
2. List any candidate fields
3. Emit a JSON fragment matching the schema

The CoT scratchpad is discarded; only the JSON is parsed. This both improves extraction accuracy on legalese and gives us cheap debuggability when the schema validator rejects an output.

---

### 3.3 Multilingual Handling

TED publishes in 24 official EU languages. Rather than translate the source documents (which loses fidelity, especially for legal terms), we:

1. Keep them in their original language
2. Rely on multilingual embedding models for semantic similarity (§4.3)
3. Prompt the LLM in English with the source text appended verbatim

The LLM reads the foreign text natively; only its output is in our schema.

---

## 4. Hybrid Matching Algorithm — The Core Novelty

This is the engineering centrepiece of the project and the primary answer to the rubric's **Section 5 (Novelty / Value Proposition)**.

An off-the-shelf approach would be: *"feed the tender and the company description into an LLM and ask which company fits best."* That is the wrapper the rubric explicitly says will not score. Instead, we decompose the matcher into independent layers, each of which uses the right tool for the job:

| Layer | Tool | Role |
|-------|------|------|
| Field extraction | LLM | Extracts structured fields — does NOT rank |
| Semantic similarity | Open-source embedding ensemble | Computes semantic match score 0–100 |
| Budget / location / certs | Deterministic rules | Hard-criteria scoring |
| Weight optimisation | Logistic regression | Learns weight priors from award history |

---

### 4.1 Pipeline Overview

```python
candidates  = past_winners(tender.cpv, tender.buyer)        # §5.1
                ∪ web_search_candidates(tender)              # §5.2 fallback

candidates  = disqualifier_filter(candidates, tender)        # §4.2 (hard filter)

for c in candidates:
    sem    = semantic_score(c, tender)                       # §4.3 (Sentence-BERT ensemble)
    rules  = rule_score(c, tender)                           # §4.4 (budget/loc/certs)
    past   = past_win_score(c, tender)                       # §4.5 (TED history feature)
    weights = current_weights()  # learned prior, see §4.6; user-overridable, §4.7
    score  = weighted_sum(weights, {sem, rules, past})
    explain = explanation_for(score, sem, rules, past)       # §4.8

rank candidates by score; return top-K with explanations
```

---

### 4.2 Hard Disqualifier Layer (Negative Matching)

Before we spend any compute on a candidate, **deterministic filters** remove anyone who is clearly not eligible:

- Company is on an EU procurement blacklist
- Tender requires bidders from a country list and the company is not in it
- Tender minimum-size requirement (e.g., €10M annual revenue) and the company is materially smaller
- Tender requires a specific certification (e.g., ISO 27001, CE marking) the company demonstrably lacks
- Company has explicitly lost this exact tender before (re-issue case)

> 🔴 **[Claude suggestion]** For the MVP we recommend implementing only the first three filters (blacklist, country, size). Certifications and re-issue detection require richer datasets and can be added in a v2 of the matcher — listing them now under "Future Work" in the project management report is honest scope-management.

---

### 4.3 Semantic Similarity (Open-Source Embedding Ensemble)

For each surviving candidate, we compute the semantic similarity between the tender's `technical_requirements` text and the company's portfolio text (scraped from their site). We use three open-source models in ensemble:

| Model | Why Included |
|-------|-------------|
| `sentence-transformers/all-MiniLM-L6-v2` | Fast, lightweight; baseline that runs cheaply on CPU. Good as a recall stage. |
| `sentence-transformers/all-mpnet-base-v2` | More accurate English semantic baseline; sits as the precision stage. |
| `intfloat/multilingual-e5-large` | Multilingual; lets a German company match a French tender (24 EU languages on TED). |

All three are **open-source and run locally**; no API costs for the most-frequent operation in the pipeline. Each requirement vs. portfolio-snippet pair gets a cosine similarity from each model. We z-score-normalise per model and average. The final semantic sub-score is the **mean of the top-K requirement matches** — not the max, to reward broad coverage rather than one lucky overlap.

---

### 4.4 Rule-Based Scoring

Three dimensions are best handled with deterministic rules, not embeddings:

| Dimension | Logic |
|-----------|-------|
| **Budget fit** | Companies whose typical contract band (median of past TED awards) overlaps the tender's estimated budget score 1.0; partial overlap scores in (0, 1) by a piecewise-linear function; no overlap scores 0. |
| **Geographic fit** | NUTS-region match against the tender's `geographic_scope`. Same NUTS-2 region = 1.0, same country = 0.7, same EU = 0.4, otherwise scored against tender openness. |
| **Qualifications & certifications** | Boolean overlap between the tender's `required_certifications` and the certifications extracted from the company website. Each missing required cert subtracts from the sub-score; surplus certs do not add. |

---

### 4.5 Past-Win Feature

For every candidate, we look up its TED award history filtered by the same CPV and (optionally) the same buyer. We compute a small feature vector — number of wins, mean contract value, recency-weighted win rate — and condense it to a single `past_win` sub-score in [0, 1].

This is the feature the original brief was missing entirely, and it is genuinely useful: a company that has won this CPV from this buyer twice in five years is meaningfully more likely to be relevant than one that scores well on text alone.

---

### 4.6 Logistic-Regression Weight Prior

We do not hard-code the weights between `(semantic, rules, past_win)`. Instead, we train a **logistic regression** to predict *"was this company the actual winner?"* from the sub-scores `(sem, budget, geo, certs, past_win)`, using historical Award Notices as ground truth. The trained coefficients become the recommended weight prior shown to the user on the dashboard.

> 🔴 **[Claude suggestion]** Logistic regression is the right choice for this stage of the project: it is interpretable (coefficients are weights), it works on tiny datasets, and it lets us explain to the supervisor why we are using "classical ML over LLMs." If the team later wants to upgrade, gradient-boosted trees (LightGBM) on the same features are a one-week swap with no architectural change.

---

### 4.7 User-Adjustable Weights with Real-Time Recalculation

On the dashboard, sales staff see the model-recommended weights as **sliders**, with the option to override. When a slider moves, the score for every visible candidate is recomputed **client-side** from the cached sub-scores in milliseconds — no LLM round-trip.

Overrides are stored in the user's session and (optionally) saved as a named preset. Overrides are also **logged**. Periodically, we retrain the logistic regression including the user's thumbs-up/down feedback (§7.4). Over time, the recommended weights drift toward what this team actually considers a good lead.

---

### 4.8 Score Explanations

Every score returned to the user comes with a structured explanation built from the sub-scores and their evidence spans. Example, exactly mirroring the team's spec:

```
Hochtief AG — score 78 / 100
  Semantic match  : 85   (tender mentions "sensor networks"; company
                          portfolio: "wireless monitoring nodes", evidence:
                          tender doc id 12, page 7; portfolio sec. "IoT")
  Budget fit      : 60   (tender €4M; company median win €2.8M)
  Geographic fit  : 100  (NUTS-2 DE21 match)
  Certifications  : 75   (3 of 4 required certs present; missing: ISO 14001)
  Past-win bonus  : +12  (3 wins in CPV 45000000-7 in last 5 years)
  Disqualifiers   : none
```

Generation of this explanation is **templated and cheap**; it does not require an LLM call. When a sub-score involves a free-text evidence span (the semantic case), the relevant snippet is extracted directly from the sentences that produced the highest pairwise similarity — again, no LLM needed.

---

## 5. Company Discovery

### 5.1 Primary: Award-Notice Cross-Referencing

For a fresh tender on CPV X from buyer B, we first query the `awards` table for:
- Previous winners on CPV X (any buyer)
- Previous winners from buyer B (any CPV)

The union, deduplicated by canonical company ID, is the **primary candidate set**. This works because TED award notices already publish exactly this information — we just need to have ingested and entity-resolved it (§2.3).

---

### 5.2 Fallback: Wider Web Search

When the primary set has fewer than K candidates, or when the team explicitly asks for broader exploration, we issue a constrained web search:

- The query is built from the tender's top three technical requirements and its CPV name
- The search is restricted to a curated whitelist of legitimate company-listing sources
- Results are rate-limited

> 🔴 **[Claude suggestion]** Use the Bing Web Search API (cheap, predictable rate limits) for the MVP. Avoid scraping Google search results directly — it violates their ToS and is unreliable. The team should also consider the EU's own EUDAMED, ENISA, and similar sectoral registers as structured candidate sources for MedTech / Cyber, which is more defensible than free-text web search.

---

### 5.3 Company Profile Extraction

For each candidate (from either source), the agent visits the company website and extracts a structured profile:

- Technical focus areas
- Named past projects
- Certifications
- Approximate size
- Geographic presence

This is the only place LLMs do unstructured extraction over the open web; outputs are again JSON-schema-constrained.

---

## 6. Database Architecture

All artefacts live in a **single relational schema (PostgreSQL)**. The schema below is deliberately small and easy to query — it has to support the dashboard, the matcher, the feedback loop, and backtesting against past tenders, all without a NoSQL escape hatch.

### 6.1 Tables

| Table | Purpose / Key Columns |
|-------|----------------------|
| `tenders` | One row per ingested Contract Notice. Stores the structured Tender object from §3.1, plus `raw_json` for traceability. |
| `awards` | One row per ingested Contract Award Notice. Joins to a canonical company via `company_id`. |
| `companies` | Canonical company entities after entity resolution. Aliases stored in a child table. |
| `company_profiles` | Latest scraped profile per company: `tech_focus[]`, `past_projects[]`, `certifications[]`, `approx_size`. |
| `documents` | Downloaded dossier PDFs and other attachments, addressed by hash. `tender_id` FK. |
| `embeddings` | Vector store: `(object_id, model_name, vector)`. Used by the semantic matcher. We use **pgvector** to keep it in Postgres. |
| `matches` | One row per (tender, company) candidate. Stores all sub-scores, the active weight set, the final score, and a JSON explanation blob. |
| `emails` | Drafted emails. Stores `tender_id`, `company_id`, `subject`, `body`, `status` (draft/sent/replied), `evidence_refs[]`. |
| `feedback` | User thumbs-up/down events on emails or on matches. Feeds the weight learner (§4.6). |
| `weights_log` | User overrides of the weight sliders. Time-stamped and per-user. |

> 🔴 **[Claude suggestion]** Postgres + pgvector is enough. Don't introduce a separate vector DB (Pinecone, Weaviate) for the MVP — you triple your operational surface area for no benefit at this scale. Embeddings tables are easy to migrate to a dedicated vector DB later if numbers grow.

---

### 6.2 Why a Single Schema Matters

Beyond storage, this schema unlocks two evaluation moves that satisfy multiple parts of the rubric:

1. **Backtesting:** We can simulate *"if the system had been live two years ago, would it have surfaced the actual eventual winner in its top-3?"* — directly using joins over `tenders × awards × matches`.

2. **UAT instrumentation:** The User Acceptance Testing report (rubric Document 3) becomes much easier: we can hand a sales user the dashboard, log every interaction into `feedback` and `weights_log`, and analyse the result without ad-hoc instrumentation.

---

## 7. Evidence-Grounded Email Generation

Generating outreach is the user-visible payoff of the whole pipeline, and also the **highest-risk place for hallucination** — if the email tells a sales rep that a company has experience with X when it doesn't, the rep will lose credibility on the first call. We address this with a two-step generation pattern that is itself part of the project's novelty.

---

### 7.1 Step 1: Evidence Extraction

Before any prose generation, an **extractor** builds an evidence list of match points: each match point is a triple of `(tender claim, company claim, similarity score)`, every claim carrying its `evidence_span` back to a specific document and character range. The top 3–5 match points become the email's talking points. This step is **deterministic** given the matcher output — no LLM.

---

### 7.2 Step 2: Constrained Generation

The generator LLM is prompted with:

1. The tender's public summary
2. The company's name and one-line description
3. **ONLY** the evidence list from step 1

It is instructed not to introduce any factual claim outside the evidence list. We additionally **post-validate**: if the generated email contains a named entity, certification, or claim not present in the evidence list, the email is flagged for review rather than auto-sent.

---

### 7.3 Why This Is Different From an LLM Wrapper

A naive wrapper would feed both the tender and the company description into the LLM and ask it to write an email. That works in the demo and **fails in production**: the LLM interpolates plausible-sounding claims. By making evidence extraction a separate, deterministic step, and by post-validating against the evidence list, we get:

- ✅ Traceability for every claim in every email
- ✅ Useful for sales (every claim is verifiable)
- ✅ Useful for the GenAI Safety report (rubric Document 4)
- ✅ A clear engineering contribution vs. a wrapper

---

### 7.4 Feedback Loop

Every email gets thumbs-up / thumbs-down on the dashboard. Negative feedback feeds two places:

1. **The matcher's logistic-regression retraining** — a thumbs-down on a poor lead lowers the recommended weight on whatever sub-score promoted them.
2. **Few-shot example refresh** — a small labelled set of "good" and "bad" email drafts that we periodically use to refresh the examples in the email-generator prompt.

We deliberately do **NOT** fine-tune any model — the dataset is too small and the quality bar too high; few-shot ICL is the right tool here.

---

## 8. Frontend Dashboard

The dashboard is the same three-column workflow already shown in the v2 proposal's Sample Screens section:

```
Active Tenders  →  Lead Analysis  →  Email Draft
```

The new engineering surfaces:

| UI Element | Engineering Behind It |
|------------|----------------------|
| Weight sliders | Client-side recompute from cached sub-score blob — no backend round-trip |
| Per-candidate score explanation panel | Templated from the `matches.explanation` JSON — no LLM call |
| Disqualifier badge | Boolean flag from the `matches` table |
| Evidence panel (emails) | Hyperlinks into `documents` by `evidence_span` (doc_id, page, chars) |

> 🔴 **[Claude suggestion]** Given the team's preferences, build the frontend in **Vue 3 with TypeScript** and **Pinia** for state. The score-recomputation logic on the slider can run entirely in the browser from the cached sub-score blob — no backend round-trip — which is what makes the slider feel instant. Use **TailwindCSS** for styling so we don't spend project time on CSS.

---

### 8.1 Final Presentation Demo Loop

For the live demo at the Final Presentation (rubric, Final Presentation = 20 points), the demo loop is:

1. Pick an active tender
2. Show extracted sections + dossier link
3. Show the matcher's top-5 with explanations
4. Nudge a slider so the ranking visibly changes
5. Open one candidate, show evidence panel
6. Generate an email
7. Highlight that every claim in the email is hyperlinked to its evidence span

---

## 9. Mapping to Grading Criteria

Cross-checking each section of this document against the rubric (Course Project, 85% of the unit grade).

| Rubric Item | Where Addressed |
|-------------|-----------------|
| **Mid-term (10): project vision, timeline, architecture, current progress** | Architecture comes from §2–§7; timeline goes into the Project Management Report |
| **Final presentation (20): MVP demo, evaluation** | Demo script in §8; evaluation via backtesting (§6.2) and UAT (§8) |
| **User Guide (10)** | Driven primarily by the dashboard in §8 |
| **Project Management Report (20): vision, Gantt, architecture, methods incl. prompt engineering, team chart, current progress, future plans, pitch video** | Methods are §3 (prompt engineering / CoT) and §4 (hybrid matcher); architecture is §2–§7; team chart is in v2 |
| **UAT Report (10)** | Sales-staff slider use, thumbs-up/down on emails (§7.4), event log via `feedback` table (§6.1) |
| **GenAI Safety & Reflection (10)** | Evidence-grounding (§7.2–7.3), restricted-dossier handling (§2.5), entity resolution (§2.3), hard disqualifiers (§4.2) |
| **Novelty / Value Proposition (5)** | Hybrid matcher (§4) is the single largest novelty; dual TED stream (§2.1) and evidence-grounded emails (§7) reinforce it |

---

## 10. Open Questions / Suggestions for the Team

The following items are not yet resolved by the v2 proposal and should be discussed at the next team meeting.

> 🔴 **[Claude suggestion]** **Industry choice.** We've recommended Construction + Renewable Energy + IT/Cyber, but the team should validate this against availability of TED award data in the past 24 months — the matcher's logistic-regression weights are only as good as the volume of historical wins we can train on.

> 🔴 **[Claude suggestion]** **Scope of company scraping.** Aggressive scraping risks IP bans and is ethically borderline. Worth budgeting one week for a deliberate scraping policy (robots.txt respect, request rate, cache TTL) and surfacing this in the GenAI Safety report.

> 🔴 **[Claude suggestion]** **How many candidates per tender.** We assumed top-K = 5 throughout. The right K depends on what a real sales user can act on per day. The UAT (rubric Document 3) is the right place to settle this empirically.

> 🔴 **[Claude suggestion]** **Vision-LLMs over blueprints.** Mei's idea document proposes parsing construction blueprints with a Vision-LLM. That is genuinely impressive but is a project on its own. We recommend marking it as **Future Work** for the final report and not committing to it for the MVP — the rubric's Section 5 is already addressed by §4 alone.

> 🔴 **[Claude suggestion]** **Knowledge graph (Neo4j).** Mei's idea also proposes a Neo4j knowledge graph. Useful for incumbency analysis, but a full graph DB doubles operational complexity. We recommend encoding incumbency as a single feature in the `past_win` sub-score (§4.5) for the MVP, and listing the full Neo4j graph as **Future Work**.

---

*End of document.*
