# Future Decisions Required

## Agentic Flow Decision

Quick context check first: there's already a Phase 6 scaffold at [backend/app/agent/controller.py](../backend/app/agent/controller.py) ("Claude tool-use orchestrator that exposes ingestion/matching/generation as tools"), and CLAUDE.md §9 frames it as "AgentController exposes ingestion/matching/generation as Claude tools and drives multi-step workflows". So the agentic layer is already part of the plan — what hasn't been settled is *how agentic*, and where it adds real value vs. just being a thin wrapper over deterministic code.

Four ways to frame the agentic role, in increasing autonomy:

| Framing | What the agent does | Where it differs from a pipeline |
|---|---|---|
| **Tool-use shell** | User asks "find top 3 matches for the Frankfurt clinic tender", Claude picks tools (`match_tender`, `get_evidence`, `draft_email`) and returns a narrated answer. | Conversational, but the pipeline still owns the logic. |
| **Anomaly handler** | Pipeline runs deterministically (APScheduler ticks → ingest → match → draft). When something unusual happens (parse error, ambiguous winner name, novel CPV, low-confidence match), the agent gets invoked to decide. | Most of the time it's not running. When it does, it has real authority. |
| **Reflection loop** | After each end-to-end run, agent reviews the outputs ("today's 3 matches", "last week's email feedback ratings") and proposes adjustments ("the LR weights are over-emphasising location score; consider retraining"). Plus it writes a daily/weekly narrative report. | Adds the "self-improvement" angle that university juries usually like. |
| **Planner-executor** | User states a high-level goal ("find construction-tech companies in DACH that could win this week's renewable-energy tenders"), agent plans the multi-step sequence (ingest → filter CPVs → match → rank → email-draft), executes, summarises. | Most "agentic"; also the most demo-friendly. |

Implementation choices:

- **Anthropic SDK + tool use** (native, already in `requirements.txt`) — by far the simplest. Define 6-8 tools as JSON schemas wrapping the existing functions; let Claude pick the sequence. No framework dependency. This is what the scaffold already anticipates.
- **MCP (Model Context Protocol)** — newer standard for exposing tools to Claude. Would let you reuse the same tool definitions from Claude Code or Claude Desktop while developing. Useful, but not essential.
- **LangGraph / CrewAI / AutoGen** — heavier multi-agent frameworks. Probably overkill for a single-orchestrator pipeline; adds dependencies and a learning tax without obvious payoff at this scale.
- **Anthropic computer-use** (beta) — could attack the portal-scraping problem we discussed earlier by literally driving a browser. Cool demo material but slow, expensive, and not gating for the core pipeline.

### Recommendation

**Claude recommendation for this project specifically** — go with **Planner-executor + Reflection loop** built on the **native Anthropic SDK**. Concretely:

- `AgentController.run(user_goal: str)` opens a Claude session with ~7 tools: `ingest_contracts`, `ingest_awards`, `download_dossiers`, `find_matches(tender_id, top_n)`, `get_evidence(match_id)`, `draft_email(match_id)`, `query_db(read_only_sql)`.
- Claude plans → executes → narrates. Output saved to a `runs` table (new) so the agent can reference "what I did yesterday".
- Once a day (or post-feedback), a separate "reflection" prompt summarises recent activity + flags drift in matching quality.
- Prompt caching on the tool definitions + system prompt — keeps cost low even with many calls per run.

That hits both academic boxes — visible multi-step autonomy AND a self-improvement angle — without dragging in framework complexity. The whole agent layer is probably 2-3 files: `controller.py` (the loop), `tools.py` (schemas + dispatch), `reflector.py` (the daily narrative job).


## PDF Scraping Decision

The 4 portals we hit during testing are each a national procurement system with its own URL scheme, auth flow, and sometimes its own API. There's no single solution; the realistic options sit on a cost / generality spectrum:

| Approach | Idea | When it fits |
|---|---|---|
| **Per-portal adapters** | Hand-coded `EvergabeAdapter`, `TenderArenaAdapter` etc. — each knows that portal's URL structure, dossier endpoint, optional login flow. Use httpx + a bit of HTML parsing (lxml/selectolax). | A handful of high-volume portals. Most accurate, most maintenance. |
| **Headless browser (Playwright)** | Open the portal page in a real browser, wait for JS, click around, dump the dossier link. No LLM. | JS-heavy portals that won't render with plain httpx. Slow, brittle when sites redesign. |
| **Commercial scraping APIs** | Browserless / ScrapingBee / Bright Data / Apify / Zyte — they run the browser + rotate IPs + handle CAPTCHAs. You give them a URL, they give you HTML or extracted text. | When anti-bot defenses matter. Cost: ~$30-300/mo at low volume. Out of scope for a uni project. |
| **LLM-driven generic scraping** | [Firecrawl](https://firecrawl.dev/) (HTML → markdown) + Claude to extract "what's the dossier URL on this page?". Or [browser-use](https://github.com/browser-use/browser-use) (Playwright + LLM-driven autonomous nav). Or Anthropic computer-use (beta — Claude drives a real browser). | Long tail of unknown portals. Most general, slowest, most expensive per page. |
| **Public portal APIs** | Some national systems (`eis.gov.lv`, `tenderned.nl`, Spain's PLACSP) publish open APIs. `OpenTenders.EU` aggregates many. | Free + authoritative when available. Coverage is patchy. |

**My take for this project specifically:** worth not building this yet. The 5 tenders we have show the issue clearly — 4 of 5 `document_url`s are portal landing pages, 1 is TED's own PDF mirror. For the matching pipeline (Phase 3), you have the **full TED notice envelope** in `tenders.raw_json` already — title, buyer, CPVs, budget, multilingual descriptions. That's enough to demonstrate semantic matching + scoring. The portal dossiers would add detail (technical specs, required certifications) that improves match quality, but they're not gating for a working V1.

If/when you do build it, the lowest-risk first step is a small **adapter registry** (`PORTAL_ADAPTERS = {"evergabe.de": EvergabeAdapter(), ...}`) that we extend one portal at a time as needed, with a generic **Firecrawl + Claude** fallback for everything else. That way we never block on a hard portal and we keep LLM costs low for the long tail.

The agent frameworks (browser-use, computer-use) are interesting but I'd hold off — they're the most generic but also the slowest, most expensive, and least reliable. Better as a Phase 6+ exploration once the core pipeline ships.

