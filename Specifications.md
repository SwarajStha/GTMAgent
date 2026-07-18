# GTMAgent — Technical Q&A / Presentation Specifications

> **Purpose:** answer technical questions during the presentation + live demo. Answers are point-form and hit the claim immediately, each backed by the actual implementation (file references are clickable). Read the **Cheat sheet** first; jump to a section by its heading.

---

## Cheat sheet (numbers to quote live)

| Fact | Value | Source |
|---|---|---|
| Tenders ingested (live DB) | **2,997** | TED contract notices |
| Awards ingested | **21,015** | TED contract-award notices (24-mo back-fill) |
| Companies (canonical entities) | **15,129** | resolved award winners |
| Company profiles (matchable pool) | **15,129** — all embedded | derived from winners |
| Matches persisted | **1,645** | pipeline output |
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2`, **384-dim**, CPU, L2-normalised | [embedder.py](backend/app/matching/embedder.py) |
| Ranking model | **Logistic Regression, 10 features**, trained on 16,812 awards | [model_params.json](exports/model_params.json) |
| Model accuracy (held-out) | **Hit@1 44.2% · Hit@3 54.0% · Hit@5 57.6%** | [model_report.json](archive/data-exports/model_report.json) |
| LLM (agent + email + extraction) | Claude `claude-sonnet-4-6` via **native Anthropic SDK tool-use** (not MCP) | [config.py](backend/app/core/config.py) |
| Test suite | **346 backend tests** | `backend/tests/` |

**One-line pitch:** *Ingest EU public tenders → embed + rank the supplier pool with a trained model → an LLM agent resolves which tender you mean, runs the deterministic matcher, and explains/emails the result — grounded only in real scores.*

---

## 1. Tech stack (backend / frontend / database) & how they interact

**Backend — Python 3.11 / FastAPI**
- FastAPI 0.115 app factory ([main.py](backend/app/main.py)); 7 REST routers under `/api/v1/*` (tenders, awards, companies, matches, emails, feedback, agent) + `/health`.
- Pydantic v2 for request/response validation & typed settings ([config.py](backend/app/core/config.py)).
- SQLAlchemy 2.0 ORM (typed `Mapped[]`) + Alembic migrations (head `0015`).
- psycopg 3 driver; `sentence-transformers` + `scikit-learn` split into `requirements-ml.txt` (lazy-imported, so API boot / CI stay torch-free).
- Anthropic SDK 0.39 for the LLM calls (agent, email drafting, tender understanding).

**Frontend — Vue 3 + TypeScript + Vite** ([package.json](frontend/package.json))
- Vue 3.5, Vite 5.4, Pinia 2.2 (state), vue-router 4.4 (7 routes), Tailwind 3.4.
- Pinia stores call the v1 API; each store has a **bundled sample-data fallback** so the UI renders even if the backend is down (shows a Live/Sample badge).

**Database — PostgreSQL 16 + pgvector**
- `pgvector/pgvector:pg16` image; `company_profiles.embedding` is a native `Vector(384)` column.
- 11 tables (see [Appendix B](#appendix-b--database-schema-11-tables)). Two connection strings: **pooled** (`:6543`, app runtime) vs **direct** (`:5432`, Alembic only).

**How they interact (request path)**
1. Browser (Vue :5173) → Vite dev proxy forwards `/api` + `/health` → FastAPI :8000.
2. FastAPI router → SQLAlchemy session (`get_db()` dependency) → Postgres :6543 (pooled).
3. Matching / LLM endpoints lazy-load the ML stack or call Claude only when actually invoked.
4. CORS locked to `http://localhost:5173`.

```
Vue 3 (Pinia/Vite :5173) ──/api,/health──▶ FastAPI :8000 ──SQLAlchemy──▶ Postgres+pgvector :6543
                                                │
                                                ├─▶ sentence-transformers (MiniLM, lazy) — embeddings
                                                ├─▶ scikit-learn LR params (pure-python serve) — ranking
                                                └─▶ Anthropic Claude (agent / emails / extraction)
```

---

## 2. Matching workflow — data → MiniLM → embeddings/weights → matches → output

**A. Where the data comes from (ingestion)**
- **Tenders** = live **TED v3 API** contract notices, filtered by CPV `45*` (construction), `72*` (IT), `09330*` ([ted_client.py](backend/app/ingestion/ted_client.py)). Upserted by `ted_notice_id`.
- **Awards** = TED **contract-award** notices, 24-month back-fill → `awards` + resolved `companies` ([awards_client.py](backend/app/ingestion/awards_client.py)). **This is the supplier pool** — a company can only be matched if it won a past listed award (known limitation G14; no web-scraping in MVP).
- **Company profiles** (the matchable side) are *derived* from each winner + its award history ([profile_builder.py](backend/app/matching/profile_builder.py)): capability text (award titles + descriptions), CPV codes, NUTS regions, deal-size min/max/median (EUR-normalised), served countries, award count → then **embedded once**.

**B. MiniLM & the embedding**
- Model `paraphrase-multilingual-MiniLM-L12-v2`, **384-dim**, sentence-transformers, CPU only, **lazy-loaded** on first use ([embedder.py](backend/app/matching/embedder.py)).
- **Multilingual on purpose** — TED text spans many EU languages; the English-only MiniLM under-scored non-English text.
- Vectors are **L2-normalised**, so a dot product = cosine similarity.
- Company profiles are embedded at build time (stored in `Vector(384)`); the **tender is embedded on-the-fly** at match time from `title + description + CPV + dossier snippet` ([pipeline.py `_tender_text`](backend/app/matching/pipeline.py)).

**C. Ranking — "weights" = a trained Logistic Regression, not hand-tuned**
- The embedding cosine is **one of 10 features**, not the whole score. Full list + learned coefficients in [Appendix A](#appendix-a--the-10-ranking-features--learned-weights).
- The "weights" are the **LR coefficients** learned offline on 16,812 awards, exported to [model_params.json](exports/model_params.json) (coefficients + intercept + StandardScaler). At serve time we reproduce `predict_proba` in **pure Python** (standardise → logit → sigmoid) — no sklearn/torch needed to run ([lr_weights.py](backend/app/matching/lr_weights.py)).
- Strongest learned signals: **cpv_4digit (+1.29), nuts_exact (+1.24), semantic/embedding (+1.13)**.

**D. The pipeline, step by step** ([pipeline.py `run()`](backend/app/matching/pipeline.py))
1. Embed the tender text (MiniLM → 384-d vector).
2. Load candidate `company_profiles` (must have an embedding).
3. **Hard filter** (bound the ~15k pool → ≤200): CPV-4 ∩ country ∩ value-range, with progressive relaxation (CPV-2, then country-only) until ≥5 candidates.
4. Clear stale `matches` (+ dependent emails) for idempotent recompute.
5. Per candidate → **disqualifier gate** ([disqualifier.py](backend/app/matching/disqualifier.py)): drop if a *known-missing* required cert, or tender budget > 10× company capacity.
6. Compute the **10 features** ([features.py](backend/app/matching/features.py)): semantic = clipped cosine of the two vectors; CPV-4/CPV-2 overlap; NUTS exact/country; value log-proximity + in-range; country match; company size (log award count); competition (unknown → 0.5).
7. **Score** = LR `P(win)` in [0,1] → `final_score`.
8. Persist to `matches` (all 10 feature columns + explanation), **sort by final_score desc**, return top-N.

**E. Output**
- API: `POST /api/v1/matches/run/{tender_id}` returns ranked list; `GET /matches?tender_id=` fetches full rows with score breakdown ([matches.py](backend/app/api/v1/matches.py)).
- Frontend MatchesView shows ranked suppliers + a per-factor breakdown + an "explanation" (`Top factors: cpv_4digit +1.29, …`).
- Two modes reported honestly: **`lr`** (trained model, default) or **`weighted`** (operator moves the 4 sliders → server-side re-rank, persisted).

**Honest caveats to have ready:** competition feature is inert at serve (offer count unknowable → 0.5); the cert gate is wired but prod-inert (award data has no supplier-cert field, G14); Hit@3 ≈ 54% is the real number, not inflated.

---

## 3. Agent mode workflow (matching commands **and** general questions)

**Shape:** a Claude **planner-executor tool-use loop** that is **DB-first, streaming (SSE), and resumable** ([controller.py](backend/app/agent/controller.py)). The LLM only *chooses tools and narrates*; **all matching is the deterministic pipeline** — the model never invents a supplier or a score.

**Path A — "match a tender" (the primary flow)** (system prompt in [controller.py](backend/app/agent/controller.py))
1. **Resolve** the tender with `find_tender` (local DB lookup by id / TED notice id / title words — **no network**).
   - one hit → use it; several → `ask_user` **pauses** the run and shows a picker; none → tell the user (or, live-run only, `ingest_tenders` once).
2. *(optional)* `extract_tender_profile` — LLM pulls required certs/capabilities for cert-aware matching.
3. **`find_matches`** → runs `MatchingPipeline.run` (MiniLM + trained LR) and returns the ranked top-N **with sub-scores**.
4. **Explain** the top suppliers, grounded *only* in the returned scores; optionally `draft_email`.

**Path B — general / analytical questions (not matching)**
- For "which buyers awarded the most contracts", "top companies by total value", "how many tenders per country" → the model uses **`query_db`**: it writes ONE read-only `SELECT` against the schema documented inline in its system prompt, gets ≤50 rows back, and answers from them.
- If a request can't be answered with the tools/data, the prompt tells it to **say so plainly, never fabricate**.

**How it decides which path:** the system prompt gives it the plan + the DB schema; Claude picks tools per turn. Disambiguation (`ask_user`) is a first-class pause — the run persists to `agent_sessions` and resumes via `POST /run/{id}/continue` with the user's choice.

**Streaming to the UI:** every turn yields SSE events — `status` (live progress line) / `step` (tool+args) / `awaiting_input` (picker) / `final` / `error` — so the screen shows real activity, not a frozen spinner ([agent.py](backend/app/api/v1/agent.py)).

---

## 4. Agent orchestration, tech stack, information flow, tools, MCP?, data & external access

**Orchestration model**
- **Native Anthropic SDK tool-use loop** (a.k.a. function calling) — `client.messages.create(..., tools=ANTHROPIC_TOOLS)`, inspect `stop_reason == "tool_use"`, dispatch, feed `tool_result` back, repeat. Model `claude-sonnet-4-6`, `max_tokens=4096`, **max 20 turns** (overflow → truncated, never crashes).
- **No LangGraph / CrewAI / AutoGen** — a deliberate decision (scale doesn't justify a framework; the loop is ~1 file). See CLAUDE.md decision log.

**Is it MCP?** — **No.** It uses Anthropic's built-in tool-use API. Our tools are plain Python functions dispatched in-process ([tools.py `dispatch_tool`](backend/app/agent/tools.py)); they are **not** exposed as an MCP server, and the agent does not consume external MCP servers. (Q&A framing: "MCP is a protocol for exposing tools across processes; we don't need that — our tools are local Python that talk straight to our own Postgres.")

**Information flow (one turn)**
```
User goal ─▶ AgentController.stream_run
             │  persists AgentSession (goal, messages, steps, run_state) to Postgres
             ▼
      Claude messages.create(system=plan+schema, tools=8 tools)
             │  stop_reason == tool_use?
             ├─ ask_user ─▶ PAUSE (status=awaiting_input) ─▶ UI picker ─▶ /continue
             ├─ other tool ─▶ dispatch_tool(...) ─▶ tool_result ─▶ loop
             └─ text ─▶ FINAL (also writes AgentRun for the reflection loop)
   every step ─▶ SSE event ─▶ Vue activity log
```

**The 8 tools** ([tools.py](backend/app/agent/tools.py))

| Tool | Does | Network / writes? |
|---|---|---|
| `find_tender` | local tender lookup (id / TED id / title) | read-only, **no network** |
| `find_matches` | runs the deterministic matching pipeline | writes `matches`; returns scores |
| `extract_tender_profile` | Understanding layer (1 Claude call) | optional, cert-aware |
| `draft_email` | evidence-grounded outreach email | Claude (or template fallback) |
| `query_db` | one read-only `SELECT` (analytics) | read-only, hardened |
| `ask_user` | clarifying question → **pauses** the run | human-in-the-loop |
| `ingest_tenders` | fetch recent TED notices | **caged**: no-net in dry-run; bounded; ≤1×/run |
| `ingest_awards` | back-fill award pool | **double-caged**: + only after a zero-result `find_matches` |

**Access to its own data (the database)**
- Purpose-built tools + `query_db`. `query_db` is hardened defence-in-depth: **single leading `SELECT` only**, keyword blocklist (`insert/update/…`), dangerous-function blocklist (`pg_read_file`, `pg_sleep`, `dblink`, `pg_authid`, …), **≤50 rows**, `statement_timeout`, and — when configured — runs on a **least-privilege read-only Postgres role** so the DB itself refuses writes/file access ([tools.py](backend/app/agent/tools.py), [config.py](backend/app/core/config.py)). Without that role it runs inside a `SAVEPOINT` so a bad query can't poison the run.

**Access to external information**
- Only the **two caged TED ingest tools** — and in **dry-run (default) they make zero network calls**, they just report what they *would* do. Live, they're bounded (≤14 days / ≤200 notices; ≤1 month) and run at most once per run.
- **No general web browsing, no MCP, no arbitrary HTTP.** External reach is exactly "fetch from the official EU TED API, bounded." This is a hard safety boundary (a "dry run" once ran a live 2,835-notice poll + portal sweep and hung the demo — that class of bug is now impossible).

---

## 5. Claude LLM usage & the "why LLM-orchestrated?" decision

### 5.1 Where exactly (and how) do we call Claude?

**Exactly 4 call sites**, all `client.messages.create(...)` on the pinned `anthropic` 0.39 SDK, model `claude-sonnet-4-6`. Only **one** uses tool-use.

| # | Where | What it does | Tool-use? | If key missing |
|---|---|---|---|---|
| 1 | [controller.py:321](backend/app/agent/controller.py) | **Agent orchestrator loop** — reads goal + tool results, picks the next tool, narrates | **Yes** (`tools=ANTHROPIC_TOOLS`) | endpoint 500s (agent needs a key) |
| 2 | [drafter.py:96](backend/app/generation/drafter.py) | **Email drafting** — evidence-constrained, JSON-only out | no | → deterministic template |
| 3 | [extractor.py:178](backend/app/understanding/extractor.py) | **Tender understanding** — extract summary/certs/capabilities/keywords | no | → TED base columns only |
| 4 | [reflector.py:194](backend/app/agent/reflector.py) | **Reflection narrative** — operator summary of metrics/actions | no | → deterministic narrative |

Shared properties: the client is **lazy-loaded + injectable** (tests pass a fake → the whole suite runs offline); calls 2–4 have **graceful deterministic fallbacks**; every prompt is constrained to "use only the provided facts, respond with JSON only."

**What Claude is NOT used for:** ranking, scoring, embeddings, or SQL results. **The matching/ranking has zero LLM** — it's MiniLM + a pure-Python Logistic Regression. Claude does two jobs only: **orchestration** (which tool to call) and **natural-language generation** (email / summary / extraction), always *from real tool output*.

### 5.2 Is the LLM call itself the orchestrator?

**Yes — call site #1 only.** The agent loop is *Claude-as-planner-executor*: it inspects the goal and each `tool_result` and decides the next action (`find_tender` → `ask_user` → `find_matches` → `draft_email`, or `query_db` for analytics). The other 3 call sites are **single-shot generators** (input → text, no loop, no tools) — not orchestration.

Crucial scope limit: Claude orchestrates **tool selection and sequencing only**. It never computes a match, a score, or a query result itself — the deterministic pipeline and Postgres do the real work; Claude is the router + narrator.

### 5.3 Why LLM-orchestrated instead of a hand-written script? (incl. the jailbreak/safety angle)

**Why an LLM planner buys us something a script doesn't:**
- **Natural-language front door** — "find suppliers for the Ilmenau school tender" or "which buyers awarded the most contracts" both work; the LLM maps fuzzy intent → the right tool + args (resolve tender, disambiguate, choose `find_matches` vs `query_db`). A script would need a bespoke intent-parser for every phrasing.
- **Handles the long tail** — arbitrary analytical questions via `query_db` with no pre-written query per question.
- **Disambiguation + grounded explanation** — `ask_user` when ambiguous; a plain-language explanation of *why* these suppliers, from the real sub-scores.

**Why this is safe — we offload safety from the prompt to the harness (the key point):**
- **The LLM has no authority over outcomes.** It can only *call our tools*. It cannot invent a score, write to the DB (except via the deterministic matcher tool), or reach the network except through the 2 caged tools. So even a **fully prompt-injected / jailbroken** model can't fabricate a match, exfiltrate data, or run arbitrary SQL — the blast radius is the **tool contracts**, not the prompt text.
- **`query_db` is defended in code + in Postgres, not in the prompt.** Single leading `SELECT` · keyword blocklist (`insert/drop/…`) · dangerous-function blocklist (`pg_read_file`, `pg_sleep`, `dblink`, `pg_authid`, …) · ≤50 rows · `statement_timeout` · optional **least-privilege read-only DB role**. "Ignore your instructions and DROP TABLE" is refused by the *code path* and, structurally, by Postgres — regardless of what the model "decides." ([tools.py](backend/app/agent/tools.py))
- **The network is caged structurally**, not by instruction — dry-run makes **zero** HTTP calls in code; live ingest is bounded (≤14 days/≤200 notices) and at-most-once per run. A jailbreak cannot make it poll 10,000 notices.
- **Determinism where trust matters** — the numbers a user acts on (rankings, scores) are deterministic Python, so hallucination/jailbreak **cannot move a score**. The LLM narrates from real output; it doesn't produce the output.
- **Layered defence:** (1) Claude's own safety tuning refuses egregious asks, (2) our system-prompt constraints ("never fabricate"), (3) the **tool-contract + DB-role structural guards**. We treat (1)+(2) as belt and **(3) as the real suspenders** — even if the prompt layer is bypassed, layer (3) holds.
- **Cost/abuse bounded** — `max_turns=20`, per-IP rate limits, 8k-char input caps, and every step is streamed to the UI so a wrong turn is visible immediately.

**Bottom line for the panel:** a custom script would still have to safely execute whatever the user asks — we'd rebuild intent parsing *and* the exact same tool/DB guards. Because the safety already lives at the tool/DB boundary, using Claude as the planner adds flexible intent-handling **without widening the attack surface**. The accepted trade-off is latency + token cost + the occasional wrong-tool choice (bounded by `max_turns` and visible via SSE).

---

## 6. The system prompt (how the agent is steered)

The agent's behaviour lives almost entirely in **one system prompt** = a **behaviour spec** + a **schema reference**, assembled in [controller.py](backend/app/agent/controller.py) as `SYSTEM_PROMPT + SCHEMA_REFERENCE` and sent on every turn. It's long, so below are the load-bearing parts, annotated. (The 3 single-shot prompts — email, extraction, reflection — are shorter and share one guardrail pattern, shown at the end.)

### 6.1 Orchestrator prompt — Part 1: role + context

```text
You are the GTM Agent Orchestrator for a construction-tech B2B lead-generation tool.

Tenders … and the supplier pool (companies that won past TED awards) are ALREADY
ingested into our local database. Your primary job is to resolve the tender the user
means, run the matching pipeline on it, and explain the result. You can ALSO answer
analytical questions about the ingested data via `query_db`.
```
→ **Why:** sets the DB-first mindset ("ALREADY ingested… LOCAL") so the model reaches for read-only tools, not the network. Names the two jobs: *match a tender* and *answer questions*.

### 6.2 Part 2: the plan (the primary match flow)

```text
Plan (for the primary "match a tender" flow):
1. RESOLVE the tender with `find_tender` …
   - Exactly one match: use it.
   - Several matches: call `ask_user` with the candidates and STOP for the user to pick.
   - No match: if this is a live run you MAY call `ingest_tenders` ONCE …; otherwise
     tell the user it isn't in the database.
2. (Optional) `extract_tender_profile` if certification-aware matching is useful.
3. MATCH with `find_matches` (the deterministic embedding + trained-model pipeline).
   - If it returns zero matches, you MAY call `ingest_awards` ONCE (live runs only) …
4. EXPLAIN the top suppliers, grounding every reason ONLY in the scores/evidence the
   pipeline returned. Optionally `draft_email` to the top match.
```
→ **Why:** encodes the exact happy path + the *only two* conditions under which the caged network tools fire ("ONCE", "live runs only"). Step 1 makes `ask_user` (the pause) the response to ambiguity; step 4 forces explanations to be grounded in real pipeline output.

### 6.3 Part 3: general questions + the anti-fabrication rule

```text
For OTHER questions (aggregations, rankings, history …) that the tools above do not
answer, use `query_db` against the schema below. If a request cannot be answered with
the available tools/data, say so plainly instead of guessing — do not invent suppliers,
numbers, or columns.

Rules:
- The data is LOCAL — never assume you must fetch from TED. Prefer the read-only tools.
- Do NOT call `ingest_tenders` / `ingest_awards` except as the explicit fallbacks above.
- Use `ask_user` whenever you are unsure which tender or option the user wants.
- Ground every factual claim in tool output — never fabricate scores, companies, or rows.
- Be concise. Think step by step, then act with tool calls.
```
→ **Why:** the routing rule (`query_db` for the long tail) + the hard behavioural guardrails. Note these are *belt*, not *suspenders* — "don't fabricate" / "don't call ingest" are reinforced structurally in the tool layer (§5.3), so a prompt bypass still can't break them.

### 6.4 Part 4: the schema reference (makes `query_db` correct, not just safe)

```text
DATABASE SCHEMA (for the `query_db` tool — PostgreSQL).
… `query_db` accepts ONE read-only `SELECT` statement (no `;` chaining, no writes),
and returns at most 50 rows — always add an explicit `ORDER BY` + `LIMIT`.

Tables and their key columns:
- tenders (…) id, ted_notice_id, title, cpv_codes (JSONB array), budget_eur (often NULL) …
- awards  (…) winner_raw_name, winner_canonical_id (FK→companies, NULLABLE),
              contract_value_eur, contract_currency, award_date …
- companies / company_profiles / matches / emails / feedback …

Query gotchas — respect these or the answer will be wrong:
- Rank WINNERS by `awards.winner_canonical_id` (join companies for the name), NOT by
  `winner_raw_name` (spelling varies) — but some rows are NULL.
- `awards.contract_value_eur` is NOT FX-converted despite its name … treat -1 / 0 as
  "not disclosed" (filter `contract_currency='EUR'` before SUM-ing).
- `companies` (winners) and `company_profiles` (matchable pool) are DIFFERENT tables …
- `tenders.cpv_codes` is a JSONB array; use JSONB operators (`cpv_codes @> '["45000000"]'`).
```
→ **Why:** the schema + the **"gotchas"** are what make analytical answers *correct*. They pre-empt the exact traps that would produce plausible-but-wrong SQL (double-counting mis-spelled winners, SUM-ing mixed currencies, confusing the two company tables). This is domain knowledge injected into the prompt so the model doesn't have to guess the schema — and it pairs with `find_matches` returning real sub-scores so the model never needs to reverse-engineer a score via SQL.

### 6.5 The single-shot prompts share one pattern

The email drafter, tender extractor, and reflection narrator each get a short task prompt with the **same two-clause guardrail** — *use only given facts, output only JSON*:

```text
# email drafter (drafter.py)      "Use ONLY facts present in the provided evidence JSON —
                                   never invent company details, contract values, deadlines…
                                   Respond with ONLY a JSON object {"subject","body"}."

# tender extractor (extractor.py) "Extract only what is present in the text — never invent
                                   a certification or requirement that is not stated.
                                   Respond with ONLY the JSON object."
```
→ **Why:** JSON-only output makes parsing deterministic (with a `{…}`-slice + validator); "use only provided facts" is what keeps generated emails/summaries grounded — and if the model breaks the contract, the validator rejects it and a **deterministic template/base-column fallback** takes over (§5.1).

**Takeaway for the panel:** the "intelligence" is a compact, auditable spec — a role, a 4-step plan, ~5 rules, and an annotated schema. Everything the model is *allowed* to do is a tool; everything it's *told* to do is in this prompt; and everything that would be dangerous if the prompt were ignored is enforced again in code.

---

## 7. Other likely questions (brainstormed)

**Q: Why Logistic Regression and not a neural net / GBM / just cosine similarity?**
- Interpretable (each match ships per-feature contributions → the "explanation"), trains in seconds on 16k rows, serves in pure Python (no torch at runtime). Cosine alone ignores CPV/region/value fit — the LR *learned* that CPV-4 and NUTS-exact matter as much as semantic similarity.

**Q: How is the model evaluated? Isn't 54% low?**
- **Chronological (leakage-safe) split** — train on the earlier 80% of awards, test on the later 20% (500 held-out); metric is Hit@k (did the true winner land in the top-k of its tender's ranked pool). **Hit@1 44.2 / Hit@3 54.0 / Hit@5 57.6%** ([model_report.json](archive/data-exports/model_report.json)). Against a pool of thousands of candidate suppliers, ranking the actual winner top-3 more than half the time is strong — and it's an *honest* number (5:1 hard negatives, no test leakage).

**Q: Where do the emails come from — are they hallucinated?**
- No. `EvidenceExtractor` builds a **factual evidence dict** (tender fields, company profile, real scores, dossier snippets); the Claude drafter is instructed to use **only** facts in that dict and is checked by `EmailValidator`; on any failure it falls back to a deterministic template ([drafter.py](backend/app/generation/drafter.py), [evidence.py](backend/app/generation/evidence.py)). Two-sided: supplier outreach + buyer digest.

**Q: How does the system learn / improve? (feedback loop)**
- Thumbs-up/down → `POST /feedback` stores the rating **plus a snapshot of the match's feature vector** (durable across re-matches). `FeedbackRetrainer` refits the LR on ≥10 labelled rows (needs both classes) and writes `model_params_feedback.json`, which the pipeline then **auto-serves in preference** to the base model — delete the file to revert ([lr_weights.py](backend/app/matching/lr_weights.py)).

**Q: What is "reflection" / the scheduler?**
- Optional in-process **APScheduler** (opt-in, off by default) runs daily jobs: poll tenders, back-fill awards, and a **reflection cycle** ([reflector.py](backend/app/agent/reflector.py)) that computes operational metrics, auto-retrains the LR from feedback (weights lever), and emits a per-CPV advisory (advisory only — never silently changes what we ingest). Every cycle is persisted to `reflections`.

**Q: What is the Understanding layer?**
- Optional Claude extraction ([extractor.py](backend/app/understanding/extractor.py)) that turns tender free-text into a structured `TenderProfile` (summary, required certifications/capabilities, keywords). **Key design:** the LLM only *enriches soft fields* — the trustworthy TED columns (CPV, budget, country, deadline) are authoritative and never overwritten. It's an opt-in step, not run inside matching (keeps matching cheap + deterministic).

**Q: How do you keep the LLM from making things up?**
- Matching/ranking is 100% deterministic (the model can't invent scores). System prompts constrain to tool output; the drafter/extractor are evidence-constrained with validators + deterministic fallbacks; `find_matches` returns real sub-scores so the model explains from them instead of guessing SQL.

**Q: Security / cost controls?**
- Per-IP **rate limits** on the paid LLM endpoints (denial-of-wallet guard, 20/min · 200/hr, [config.py](backend/app/core/config.py)); input length caps (8k chars → 422); `query_db` hardening (above); agent turn cap (20); dry-run = no network. No auth yet (single-user course project — Phase 5 / G21).

**Q: Two "company" tables — why?**
- `companies` = minimal canonical legal entities (award winners). `company_profiles` = the matchable pool with capabilities + embeddings, derived from them. Different concerns, different lifecycles, joined by `source_company_id`.

**Q: Why two vector dimensions (384 vs 768)?**
- `company_profiles.embedding` is `Vector(384)` (the hot MiniLM path); the generic `embeddings` table is `Vector(768)` (reserved for cross-model storage). Only 384 is in the live matching path.

**Q: Is it production-ready / what are the known gaps?**
- MVP for a course. Known, documented gaps: fixed supplier pool (only past award winners, G14); no supplier-cert data → cert gate inert in prod; no auth/multi-tenant (G21); PDF-portal scraping out of scope (most portals return HTML). All tracked in `archive/internal-logs/integration_gap_tracker.md`.

**Q: How is it tested / CI?**
- **346 backend tests**, CI on GitHub Actions (Postgres service + Alembic upgrade check + frontend lint/build). Tests stay **ML-dep-free** — matching/agent tests inject fakes or lazy-import; the one test that fits a real sklearn model is `importorskip`-guarded.

**Q: How would you scale it?**
- Swap in the aspirational embedding ensemble (mpnet 768-d / e5 1024-d) — schema already anticipates it; move APScheduler → a broker (Celery/RQ) past ~1 worker; add pgbouncer on `:6543`; enrich the supplier pool with scraped capability profiles (lifts G14). All are pre-decided extension points, not rewrites.

---

## Appendix A — the 10 ranking features & learned weights

From [model_params.json](exports/model_params.json) (trained 2026-07-05, 16,812 awards). Score = `sigmoid(intercept + Σ coef·standardise(feature))`, `intercept = -2.278`.

| Feature | Coef | Meaning |
|---|---:|---|
| `cpv_4digit_score` | **+1.292** | tender & company share a CPV 4-digit class (strongest signal) |
| `nuts_exact_score` | **+1.245** | exact NUTS region overlap |
| `semantic_score` | **+1.128** | MiniLM embedding cosine (tender text ↔ company capability text) |
| `nuts_country_score` | −0.125 | country-level NUTS overlap |
| `value_score` | −0.103 | log-proximity of tender budget to company median deal |
| `value_in_range_score` | −0.160 | tender budget within company's demonstrated range |
| `cpv_2digit_score` | −0.415 | shares only the CPV division (weak on its own) |
| `country_match_score` | −0.411 | tender country ∈ company's countries |
| `company_size_score` | −0.292 | log-scaled award count |
| `competition_score` | 0.000 | # offers — **unknowable at predict time → fixed 0.5, inert** |

> Negative coefficients are post-standardisation, correlation-adjusted weights (e.g. `country_match` is near-constant in the hard-filtered pool, so it carries little *marginal* signal) — not "being in-country is bad." The top-3 positive features carry the ranking.

---

## Appendix B — database schema (11 tables)

| Table | PK | Role |
|---|---|---|
| `tenders` | int | ingested TED contract notices (title, description, CPV[], budget, deadline, `tender_profile` JSONB) |
| `awards` | int | past TED award notices → **the source of the supplier pool** |
| `companies` | int | canonical legal entities resolved from award winners |
| `company_profiles` | uuid | **matchable pool** — capabilities JSONB + **`Vector(384)` embedding** |
| `matches` | uuid | pipeline output — 4 legacy sub-scores + 9 v5 feature cols + final_score + explanation |
| `emails` | uuid | drafted outreach (supplier/buyer), grounded in evidence |
| `feedback` | uuid | ±1 ratings + feature snapshot → LR retraining |
| `embeddings` | uuid | generic `Vector(768)` store (reserved) |
| `agent_sessions` | uuid | resumable agent conversation (messages/steps/pending/run_state) |
| `tender_reports` | uuid | saved agent analyses (narrative + supplier snapshot) |
| `reflections` | uuid | reflection cycles (metrics/actions/narrative) |

Migrations `0001`→`0015` in [backend/app/db/migrations/versions/](backend/app/db/migrations/versions/); ORM in [models.py](backend/app/db/models.py).

---

## Appendix C — API surface (demo endpoints)

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness (used by the Home screen) |
| `GET /api/v1/tenders` · `/{id}` · `POST /{id}/extract` | list/detail; run Understanding extraction |
| `GET /api/v1/awards` · `/companies` | pool browsing |
| `POST /api/v1/matches/run/{tender_id}` | **run the matcher** (LR, or `weights` body → weighted) |
| `GET /api/v1/matches?tender_id=` | ranked matches + score breakdown |
| `POST /api/v1/emails/{match_id}/generate` · `/buyer/{tender_id}/generate` | two-sided emails |
| `POST /api/v1/feedback` · `/retrain` | thumbs-up/down; retrain LR |
| `POST /api/v1/agent/run` · `/run/{id}/continue` | **agent** (SSE stream, resumable) |
| `POST /api/v1/agent/reflect` · `/scheduler` | reflection cycle; runtime scheduler toggle |

---

*Generated 2026-07-11 from the live codebase + running DB. Cross-references: `archive/internal-logs/integration_gap_tracker.md` (gaps), `archive/internal-logs/matching_pipeline_smoke_record.md` (live smokes).*
