# GenAI Safety and Reflection Report — GTM Agent

**TUM · CITHN2014 — Foundations and Applications of Generative AI · Project 4**

> **Document status:** DRAFT / structural backbone. Page budget (rubric):
> **≤ 3 pages** excluding title/contents. Two required parts: **Safety of GenAI**
> (considerations + mitigations) and **Lessons learned / reflections** (through the
> lens of the project's KPIs and deliverables). **`[NEEDS INPUT]`** marks
> team-supplied facts.

> **── Sync update 2026-07-23: aligned to the current codebase (post-G20/G23/G25/G27) ──**
> **Peers: review each item, then delete this block before submission.**
> - **§2.4 (Reflection against KPIs)** — filled in with the real 2026-07-05 backtest
>   (Hit@1 44.2% · Hit@3 54.0% · Hit@5 57.6%) and an honest reflection on why more
>   training data didn't move the number. Confirm the framing.
> - **§1.2** — added an honest caveat on the new runtime scheduler toggle / ops
>   console (G27): it's currently unauthenticated (single-operator demo).
> - **§1.5** — noted the train/serve feature-contract drift guard (G20) as a
>   reliability control.

---

## 1. Safety of GenAI

GTM Agent uses GenAI in three roles — orchestration agent, evidence-grounded email
drafting, and structured field extraction (the Understanding layer) — and uses
open-source ML for ranking. Each role introduces specific risks, which the team
addressed with concrete, code-level mitigations rather than policy statements alone.

### 1.1 Hallucination and factual integrity (highest-priority risk)

**Risk.** The most damaging failure for a sales tool is an outreach email that
asserts a company has experience it does not have, or cites a tender detail that is
wrong — the sales rep loses credibility on the first call.

**Mitigations (implemented).**

- **Evidence-first generation.** A deterministic `EvidenceExtractor` builds the
  fact list (real TED notice ID, CPV codes, deadline, match sub-scores, company
  award history) *before* any prose is written. The LLM is prompted with **only**
  that evidence and instructed to introduce no claim outside it. The LLM ranks
  nothing and invents nothing — it phrases pre-verified facts.
- **Post-generation validation.** An `EmailValidator` checks the draft; any
  unsupported named entity or claim flags the draft for human review instead of
  presenting it as final.
- **Deterministic fallback.** If the LLM call fails, the API key is missing, or
  validation fails, the system falls back to a deterministic template assembled
  from the same evidence — verified live (a missing-prefix API key correctly
  triggered the safe fallback).
- **Human-in-the-loop.** The system never sends email; it only drafts for review.

### 1.2 Agent autonomy and unintended actions

**Risk.** A tool-use agent that can ingest data, write to the database, and call
external APIs could take destructive or expensive actions from a casual prompt.

**A real incident that hardened the design (worth stating honestly).** An early
version relied on a single guard — `dry_run=true` by default — believed to make the
write-capable tools safe. A live demo proved it insufficient: `dry_run` only skipped
the *database write*, not the *network*, so a casual goal naming a tender in prose led
the agent to a live multi-thousand-notice TED poll **and** a bulk document-portal
sweep, draining LLM credits and hanging the request. This surfaced a general lesson —
*a safety flag is only as good as the narrowest thing it actually gates* — and the
agent was reworked into a layered guard set:

- **Dry-run now means NO network.** The two remaining network tools (`ingest_tenders`,
  `ingest_awards`) short-circuit before any HTTP call in dry-run and report what they
  *would* do. A live run is **bounded** (capped look-back window + row limit) and
  permitted **at most once per goal**, and `ingest_awards` is additionally gated on a
  prior empty match result. The destructive bulk-download tool was **removed** from the
  agent entirely.
- **DB-first by construction.** The agent resolves a tender against the *local*
  database and runs the deterministic matcher; it has no general "go fetch from the
  internet" capability, so the default behaviour is inherently offline.
- **Human-in-the-loop on ambiguity.** When a request is ambiguous (e.g. a partial
  tender name), the agent **pauses and asks the user to choose** rather than guessing —
  a confirmation step before it commits to a tender.
- **Read-only, transaction-isolated database tool.** `query_db` is restricted to a
  single leading `SELECT` with a whole-word write-verb blocklist (`insert`, `update`,
  `delete`, `drop`, `alter`, `truncate`, `create`) and a 50-row cap, and runs inside a
  savepoint so even a malformed query cannot corrupt the session — the agent cannot
  mutate or exfiltrate data at scale.
- **Bounded loops + auditability.** The loop is capped (max 20 turns, partial progress
  on overflow); every run persists to `agent_runs`, and the full resumable conversation
  to `agent_sessions`, for review.

**Honest caveat — operator controls are not yet authenticated.** Separate from the
agent's own tools, the dashboard exposes an operator command console (`/retrain`,
`/reflect`, `/schedule on|off|status`) that can start the background scheduler or
trigger a retrain at runtime. These are *operator-invoked*, not agent-autonomous,
and each is bounded, but they are currently **ungated by authentication** — acceptable
for a single-operator demo, and a first candidate to place behind sign-in when the
(deferred) auth phase lands.

The takeaway, reinforced in §2, is that agent safety came from **removing capabilities
and constraining defaults**, not from trusting a single flag.

### 1.3 Prompt injection from untrusted content

**Risk.** Tender titles, descriptions, and dossier PDFs are attacker-influenced
text that flows into LLM prompts; a malicious notice could attempt to hijack
extraction or email generation.

**Mitigations.** The LLM's authority is structurally limited — it only emits
schema-validated JSON (extraction) or evidence-constrained prose (emails), and its
output is validated downstream, so injected instructions cannot cause ranking
changes, data writes, or unsupported claims. `[TEAM DECISION: consider adding an
explicit note in prompts that document text is untrusted data, not instructions —
document whether this was added.]`

### 1.4 Data privacy, provenance, and IP

- **Public-data-only.** All company and tender data originates from the EU's
  public TED journal; no private or scraped personal data is used.
- **No authenticated scraping.** Dossiers behind buyer-portal login walls are
  marked `restricted` for manual handling rather than scraped — an honest,
  lower-risk choice (4 of 5 test dossiers were correctly identified as portal
  landing pages and not ingested).
- **Traceability.** Raw TED payloads are retained (`raw_json`) and documents are
  content-addressed by SHA-256, so any surfaced fact can be traced to its source.

### 1.5 Cost, rate-limiting, and reliability

- Per-host 429 backoff and an inter-request delay keep TED ingestion within
  acceptable-use limits (validated across a ~22.5k-notice back-fill).
- Ranking uses local, open-source embeddings (no per-query API cost); the LLM is
  reserved for low-frequency drafting/orchestration, with prompt caching on stable
  tool/system definitions to keep cost low.
- TLS via `truststore` prevents silent failures under corporate SSL inspection.
- A **train/serve drift guard** (a CI-safe test pinning the live matcher's feature
  vector to the committed model parameters) catches the class of silent bug where
  the offline trainer and the online scorer disagree — protecting model correctness,
  not just uptime.

### 1.6 Bias and fairness

**Risk.** The matcher learns from historical award winners, which can entrench
incumbents and under-surface new entrants.

**Mitigations / honest limitations.** The disqualifier and rule layers operate on
objective criteria (CPV, budget, geography), and the model is interpretable, so
bias is *visible* rather than hidden. The team acknowledges incumbency bias as an
inherent property of award-history training data and documents it as future work
(e.g. a recency/new-entrant adjustment). `[TEAM DECISION: state whether any
de-biasing was attempted.]`

---

## 2. Lessons Learned and Reflections

Reflected through the project's stated KPIs and key deliverables (matcher
hit-rate, evidence-grounded generation, a working two-sided MVP, the four
documents).

### 2.1 What worked well

- **"Classical ML over an LLM call" was the right call.** Decomposing matching
  into embeddings + rules + a logistic regression — with the LLM confined to
  extraction and drafting — gave an explainable, cheap, and defensible system, and
  is the project's clearest novelty. It directly served the "no thin wrapper" KPI.
- **Trusting live evidence over documentation.** The TED API's real field
  vocabulary differed from the spec/docs; an iterative "probe the live API" loop
  was essential and became a reusable discipline.
- **The find-a-gap → fix → verify loop.** Live smoke tests repeatedly surfaced
  concrete, fixable defects (e.g. `qualification` scoring 0 everywhere; un-converted
  budgets producing a €1.3 B artifact), each fixed and re-verified. This
  incremental method visibly raised matcher quality (semantic cosines for relevant
  matches rose from ~0.24 to ~0.79 after enriching capability text).
- **Evidence-grounded generation paid off twice** — once for product credibility,
  once for the Safety story.

### 2.2 What was harder than expected / what to improve

- **Integration risk between parallel workstreams.** Two separately-built matchers
  (a simple in-app one and a stronger standalone "v5" model) had to be unified
  late; earlier interface agreement would have avoided rework. *Lesson:* agree on
  shared module contracts before parallel building.
- **Scope discipline.** Ambitious ideas (Vision-LLM blueprint parsing, a Neo4j
  knowledge graph, an embedding ensemble) were correctly deferred to Future Work;
  the temptation to build them mid-project was real. *Lesson:* a written
  Future-Work list is an active scope-management tool, not a footnote.
- **Sequencing "planned" components.** The structured `FieldExtractor` (Understanding
  layer) was de-prioritised for much of the project — the matcher read columns/dossier
  text directly — and only wired in late (G11). *Lesson:* be explicit early about which
  "planned" components are MVP-critical vs. deferrable, so the late ones land calmly
  rather than under deadline pressure.
- **Thin capability profiles** cap semantic quality, because profiles are built
  from award history rather than scraped company sites. A known, documented ceiling.
- **A safety flag only gates the one thing it actually wraps.** The agent's
  `dry_run` was assumed to make the write tools safe, but it only skipped DB writes,
  not the live network calls — exposed by a live demo that hung and burned credits
  (§1.2). *Lesson:* test the guard against the exact failure you fear (here, "does a
  dry run touch the network?"), and prefer **removing dangerous capabilities** over
  trusting a flag. The reworked agent (DB-first, caged/bounded ingest, human-in-the-loop
  on ambiguity, streaming + resumable) is both safer and more usable as a result.

### 2.3 Insights about GenAI

- **GenAI is most reliable when its authority is structurally constrained** — JSON
  schemas, evidence lists, read-only tools, dry-run defaults — not when it is
  trusted to "do the right thing." Safety and quality came from architecture, not
  from prompt wording alone.
- **The cheapest, most interpretable model that meets the bar usually wins.** A
  logistic regression beat the instinct to "just ask the LLM," and was easier to
  evaluate, explain, and trust.
- **GenAI as a development accelerant** (coding, documentation) was highly
  effective, but required the same discipline expected of the product: human review,
  verification of facts and citations, and explicit flagging of unknowns.

### 2.4 Reflection against KPIs

The final backtest (retrained 2026-07-05 on 80% of the award history; 500 held-out
awards — see Project Management Report §7) reports **Hit@1 44.2%, Hit@3 54.0%,
Hit@5 57.6%**. Measured against the stated final targets, **Top-1 (≥ 25%) is
comfortably exceeded and Top-5 (≥ 55%) is met**; the aspirational **Top-10 ≥ 75%**
was not separately measured, since the current backtest reports up to Hit@5 only —
an honest gap in the evaluation rather than a known miss.

The most instructive KPI finding is that **retraining on more data (50% → 80% of
awards) did not move the number** — Hit@3 stayed flat at ≈ 54% on a harder, later
held-out slice. This confirms the ceiling is *not* training-set size but **capability-
profile quality**: profiles are built from thin award-history text rather than scraped
company detail (documented in §2.2). What would most plausibly close the gap to the
75% aspiration is richer company profiles and an embedding ensemble — both catalogued
as future work — not simply more of the same data. The model is also structurally
stable across retrains (consistent coefficient signs; strongest positive signals are
CPV-category match, exact region, and semantic similarity), which is itself reassuring
for an interpretable, defensible matcher. `[NEEDS INPUT: if the team runs a Hit@10 /
MRR extension, add it here and reconcile against the Top-10 target.]`

---

## 3. Acknowledgment of GenAI Usage

This report was drafted with a Claude-based AI assistant working from the team's own
documentation and code, and from the course rubric; the team reviewed, corrected,
and approved it, completing the KPI reflection in §2.4 with real results. Within the
product, GenAI (Anthropic Claude) is used for orchestration and evidence-grounded
drafting, and open-source models for matching, as described above. `[NEEDS INPUT:
confirm wording.]`
