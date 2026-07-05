# GTM Agent — Behavior Description (for the agentic flow diagram)

> **Purpose of this file.** This is the source-of-truth description for generating a
> **flow diagram of how the GTM Agent works today** (a slide, in the same swim-lane /
> node / decision style as the project's `Architecture & Process Flow` diagram).
> It describes what the agent is, how it gets information, the tools it can call, the
> decision loop it follows, and the guardrails that keep it safe. Everything here
> reflects the **current** implementation (`backend/app/agent/`), not aspirational design.

---

## 1. What the agent is (one line)

A **planner-executor assistant** that turns a plain-English request (e.g. *"find good
suppliers for the Ilmenau school tender"* or *"which buyers awarded the most
contracts?"*) into a short sequence of **tool calls against our own local database**,
then explains the result in grounded language. The language model (Claude) **decides
which tool to call and writes the explanation** — it never invents suppliers, scores,
or numbers itself.

**Key principle: DB-first.** All the tenders and the supplier pool are already ingested
into our local database. The agent's default behavior is to *read from that database*,
not to go out to the internet.

---

## 2. Two things it can do (the two top-level branches)

The agent handles two kinds of requests, and the diagram should show them as two
branches out of an initial "classify the request" step:

**Branch A — "Match a tender" (the primary flow)**
Resolve which tender the user means → run the matching pipeline → explain the top
suppliers → (optionally) draft an outreach email.

**Branch B — "Answer a question about the data" (analytical flow)**
For aggregations / rankings / history that the purpose-built tools don't cover
(e.g. "top companies by total contract value", "how many tenders per country"), the
agent writes a **read-only SQL query** against a database schema it has been given, and
answers from the returned rows.

If a request can't be answered with the available tools and data, the agent is
instructed to **say so plainly rather than guess**.

---

## 3. How it gets information — the tools (8)

The agent has exactly **8 tools**. This table is the heart of the diagram — each tool is
a node the agent can call. Group them by what they touch (local DB read / local DB
write / model step / human / caged network).

| Tool | What it does | Touches | Network? |
|---|---|---|---|
| **find_tender** | Look up tenders already in the local DB by internal id, public TED notice id, or words in the title. Returns up to 8 candidates. **This is the resolve-first step.** | Local DB (read) | **No** |
| **find_matches** | Runs the deterministic **matching pipeline** (multilingual embeddings + trained model) to rank the best companies for a tender. Returns the top-N with their sub-scores. | Local DB (write: saves matches) | **No** |
| **extract_tender_profile** | Optional "understanding" step — uses the LLM to pull a structured profile (summary, required certifications, capabilities, keywords) from the tender text and store it. Feeds the certification gate. | Local DB (write) + 1 LLM call | **No** (local text) |
| **draft_email** | Writes an evidence-grounded outreach email to a matched company. | LLM (constrained) | **No** |
| **query_db** | Runs **one read-only `SELECT`** against the tracking database for analytical questions. This is Branch B. | Local DB (read-only) | **No** |
| **ask_user** | Pauses the whole run and asks the human a clarifying question (e.g. several tenders matched a partial name). Presents the choices. | Human-in-the-loop | **No** |
| **ingest_tenders** | **Caged fallback only.** Fetch recent tenders from the live TED API — *only* if `find_tender` found nothing **and** it's a live run. Bounded, at most once per run. | Live TED API | **Yes (caged)** |
| **ingest_awards** | **Caged fallback only.** Rebuild the supplier pool from historical award notices — *only* after `find_matches` returned **zero** matches, live runs only. | Live TED API | **Yes (caged)** |

Note for the diagram: **there is no web-search tool and no company-website scraper.**
(An earlier concept diagram showed those as "idea phase" — they were never built and
should not appear as agent capabilities.) `download_dossiers` (PDF scraping) was also
**removed** from the agent's toolset.

---

## 4. The control loop (the main flow to draw)

The agent runs a bounded **planner-executor loop** (max 20 turns). One turn:

1. **Think** — Claude looks at the goal + everything gathered so far and decides the
   next action.
2. **Act** — it either calls a tool, asks the user, or writes the final answer.
3. **Observe** — the tool result is fed back in, and the loop repeats.

### Branch A flow (draw this as the spine)

```
User goal
   │
   ▼
[find_tender]  ── resolve the tender by id / TED id / title
   │
   ├── exactly one tender ──────────────► use it
   ├── several tenders ──► [ask_user] ──► PAUSE, user picks ──► resume
   └── no tender ──► (live run only) [ingest_tenders] once ──► find_tender again
   │
   ▼
[extract_tender_profile]   (optional — only if certification-aware matching is wanted)
   │
   ▼
[find_matches]  ── the deterministic pipeline ranks the supplier pool
   │
   ├── got matches ─────────────────────► EXPLAIN top-N (grounded in the scores)
   └── zero matches ──► (live run only) [ingest_awards] once ──► find_matches again
   │
   ▼
EXPLAIN top suppliers  ──►  (optional) [draft_email] to a chosen match
```

### Branch B flow (analytical)

```
User question (aggregation / ranking / history)
   │
   ▼
[query_db]  ── one read-only SELECT against the known schema
   │
   ▼
ANSWER from the returned rows   (or: "can't answer that with the available data")
```

**Decision diamonds to include** (matching the attached diagram's style):
- "One tender / several / none?" after `find_tender`.
- "Any matches found?" after `find_matches`.
- "Live run or offline mode?" gating the two ingest fallbacks.

---

## 5. Grounding & honesty (a band across the diagram)

Every factual claim the agent makes must come from a tool result:
- Suppliers and their scores come **only** from `find_matches` (the trained pipeline).
- Analytical numbers come **only** from `query_db` rows.
- The agent is explicitly told **never to fabricate** suppliers, numbers, or columns,
  and to **say when something can't be answered**.

The LLM's role is deliberately narrow: **choose tools + explain results.** It does not
score, rank, or invent data.

---

## 6. Streaming, pausing, resuming (the UX layer)

- The run is **streamed live** to the UI (Server-Sent Events): the user sees each step
  as it happens — "Reading your request…", "Looking up the tender…", "Ranking
  suppliers…" — instead of a frozen spinner.
- On `ask_user`, the run **pauses** and the whole conversation is **saved**. When the
  user picks an option, the run **resumes exactly where it left off**. This makes the
  agent genuinely conversational / multi-turn.
- The loop is **bounded to 20 turns**; if it hits the cap it returns partial progress
  with a note (never runs away).

---

## 7. Safety cages (call these out — they're the "why it's trustworthy" story)

These matter because an earlier version of the agent hit the live TED API and bulk-
downloaded portal PDFs *during a "dry run"*, drained credits, and hung. The current
design fixes that:

1. **Offline mode = no network.** In dry-run / "offline mode", the two ingest tools make
   **no network call at all** — they only report what they *would* do. Matching still
   runs (it's all local).
2. **Bounded, once-per-run live ingest.** Even on a live run, ingest is capped (limited
   days/months + row cap) and runs **at most once**. `ingest_awards` only fires after a
   genuine zero-match result — it is not a tender finder.
3. **Read-only, sandboxed `query_db`.** Only a single `SELECT` is allowed; write verbs
   are blocked; dangerous DB functions (file access, credentials, sleep) are blocked;
   it runs on a **least-privilege read-only database role** and inside a savepoint, so a
   bad query can neither write, leak secrets, nor break the rest of the run.

---

## 8. Post-run actions (what the user can do with the result)

After the agent explains its matches, the result card offers:
- **Save results** → stores the narrative + a snapshot of the ranked suppliers (a
  permanent record for that tender).
- **Draft email** with a 🥇 / 🥈 / 🥉 selector → the user picks any of the top matches
  and the agent drafts the outreach email for that one.

---

## 9. Planned / potential future work — external-match fallback (OUT OF SCOPE)

> **Status: idea only. Not built, not on the current roadmap.** Show it on the diagram
> as a small, **greyed / dashed "future work — out of scope"** node hanging off the
> "any matches found?" decision — visually separated from the live flow so it's clearly
> not part of today's agent.

**The idea.** Today the supplier pool is fixed (past TED award winners), so if none of
them fit a tender well, the agent has nothing better to offer. A future tool would let
the agent **reach outside the local pool** when the internal match quality is too low:

1. **Trigger** — after `find_matches`, if the best internal score is **below a
   threshold (e.g. < X%)**, the agent decides the local pool is insufficient.
2. **Discover** — it makes an **LLM call to propose candidate company/buyer websites**
   relevant to this specific tender (sector, region, scope) → a shortlist of ~5–7 URLs.
3. **Scrape** — it visits/scrapes those sites to gather capability and contact
   information.
4. **Extract** — it distills **3–5 additional potential suppliers** from what it found.
5. **Merge & display** — it shows these **external candidates alongside the internal
   matches**, clearly labelled as web-sourced (and lower-confidence / unverified).

**Why it's hard (and therefore deferred).** Web scraping is not a single tool — every
website has a different structure, anti-bot protection, and language, so it needs
per-site handling, is slow, and is fragile to maintain. Grounding and verifying the
scraped claims is also non-trivial. For these reasons it stays a **future exploration
idea**, not a committed feature.

**On the diagram:** draw it as one dashed grey box labelled something like
*"[Future / out of scope] External match fallback — LLM finds candidate websites →
scrape → 3–5 extra suppliers, shown beside internal matches (only if internal score
< X%)"*, connected to the "any matches found? / score too low?" decision by a dashed
line. Keep it visually minor so it doesn't read as a live capability.

---

## 10. Suggested diagram structure (how to lay it out)

To match the house style of the existing `Architecture & Process Flow` slide, lay the
agent diagram out with the same **swim lanes** and a **legend**:

- **Lanes (top to bottom):** `USER / UI` · `AGENT (LLM decisions)` · `TOOLS & PIPELINE`
  · `DATABASE` · `EXTERNAL (caged)`.
- **Legend:** solid box = deterministic step · rounded/orange box = LLM/agent step ·
  diamond = agent decision · dashed box = caged fallback (only under conditions) ·
  cylinder = database table.
- **Main spine:** the Branch A flow in §4, left → right.
- **Side branch:** Branch B (`query_db`) peeling off the "classify request" node.
- **A pause loop** on `ask_user` back to the user lane.
- **A grounding banner** under the agent lane: *"every claim traced to a tool result —
  no fabrication."*
- **A safety callout** near the EXTERNAL lane: *"Offline mode = no network; ingest is
  caged, bounded, once-per-run."*
- **One dashed grey "future / out of scope" node** off the "any matches found? / score
  too low?" decision — the external-match fallback from §9. Keep it visually minor.

Colour the two `ingest_*` boxes and the TED API as the **only** things that ever leave
the local system, and dash them to signal "fallback only".
