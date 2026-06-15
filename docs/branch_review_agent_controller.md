# Branch review — `feat/agent-controller` (Vincent)

Merged to `main` via PR #5 (`f38b178`, 2026-06-08). First real
implementation of **Phase 6 — the agent layer**, plus nine small follow-up
commits applied directly on top after the merge (mostly Copilot-autofix
hardening, authored by Swaraj). This is exactly the design already
recommended in `docs/Notes.md` ("Planner-executor + Reflection loop on the
native Anthropic SDK, ~7 tools, 2-3 files") — so the shape of the work
matches our plan closely; what's missing is mostly downstream integration.

> **Update (2026-06-08, same day, integration pass)** — the structural gaps
> flagged in the original review (#1, #2, #4, #5, #6 below) have now been
> fixed directly on `main`. See **"Integration pass — structural fixes
> applied"** for what changed and how it was verified. The numbered Gaps
> list below is kept as a historical record (struck through where resolved)
> so the rationale for each fix stays attached to the original finding; the
> **"Remaining gaps"** section at the end is the live TODO list.

## Files added / touched

- `backend/app/agent/controller.py` — `AgentController`, the ReAct tool-use
  loop (rewritten from the Phase-1 scaffold stub)
- `backend/app/agent/controller.py.bak` — **stray backup file, checked in
  by accident** (see Gaps #2)
- `backend/app/agent/tools.py` — `AGENT_TOOLS` schemas + `dispatch_tool()`
- `backend/app/agent/reflector.py` — `Reflector`, the daily self-review job
- `backend/app/api/v1/agent.py` — `POST /api/v1/agent/run` FastAPI route
- `backend/app/db/migrations/versions/0004_agent_runs.py` — additive
  migration creating `agent_runs`
- `backend/app/db/models.py` — `AgentRun` ORM model
- `backend/app/main.py` — registers the new `agent` router
- `backend/scripts/agent_smoke.py`, `scripts/test_anthropic_schema.py` —
  smoke/debug scripts
- `backend/tests/agent/{test_controller,test_api}.py` — fully-mocked unit
  tests (2/2 passing locally)
- Collateral edits to `dossier_downloader.py` / its tests (SHA-256 dedupe
  refinement — unrelated to the agent work but bundled into the same PR)

## How it works

- **`AgentController.run(user_goal)`**: opens a `client.messages.create`
  loop. System prompt instructs Claude to plan → execute tools → review →
  summarize. Each `tool_use` content block is dispatched via
  `dispatch_tool(name, args, db_session, dry_run=self.dry_run)`, results
  appended back as `tool_result` blocks, looping until
  `stop_reason != "tool_use"` or `self.max_turns` (default 20) is reached —
  in which case the loop now stops gracefully and returns whatever it has
  with `truncated: true` *(was: raises `RuntimeError` → 500, see Integration
  pass below)*. The whole conversation runs inside one `SessionLocal()`
  context, and on completion (truncated or not) persists
  `{goal, steps, output}` to the `agent_runs` table.
- **`tools.py`** defines 6 tool schemas — `ingest_tenders`,
  `ingest_awards`, `download_dossiers`, `find_matches`, `draft_email`,
  `query_db` — and `dispatch_tool(name, args, session, dry_run=True)` wires
  each straight to the real backend module: `poll_contract_notices`,
  `backfill_awards`, `download_dossiers`, `MatchingPipeline().run()`,
  `EmailDrafter().draft()`, and a guarded raw SQL `SELECT` via SQLAlchemy
  `text()`. The three write-capable tools now forward `dry_run` through to
  their underlying functions instead of hardcoding `dry_run=False` *(see
  Integration pass below)*.
- **`query_db` guardrails**: must start with `select`, rejects `;` and a
  DDL/DML keyword blocklist, caps results to 50 rows via `fetchmany`.
- **`reflector.py`**: a separate `Reflector` class that pulls the last 10
  `AgentRun`s + last 50 `Feedback` rows, asks Claude (via a dedicated
  `REFLECTION_PROMPT`) for an operational summary — tasks executed today,
  anomalies in matching/parsing, average feedback score, and concrete
  suggestions for retraining LR weights or adjusting CPV filters. Runnable
  standalone (`python -m app.agent.reflector` style `__main__` block).
- **`agent_runs` table** (migration `0004`, additive — follows our
  established pattern): UUID PK, `goal TEXT`, `steps JSONB`, `output TEXT`,
  timestamps. This is the data substrate the reflection loop reads from.
- **`/api/v1/agent/run`**: validates `ANTHROPIC_API_KEY` is configured
  (500 if not), instantiates `AgentController`, runs synchronously, returns
  `{goal, steps, output}`.
- **`agent_smoke.py`**: CLI harness mirroring the established
  `ted_smoke.py` / `awards_smoke.py` pattern, documented in
  `scripts/README.md` with a flags table.

## Post-merge hardening already applied (9 small commits on `main`)

`Better naming convention` (fixed `find_matches`'s `tender_id` schema type
from `string`/UUID to `integer` — matches our actual `tenders.id` PK
shape), `Fix download_dossier confusion` (tool description + schema
corrected from per-tender to bulk-sweep, matching `download_dossiers()`'s
real signature), `Safer SQL payload` (added the `query_db` blocklist +
row cap), `SHA-256 matching` (dossier dedupe refinement), `Prompt
consistency` (JSON-encode the reflection activity blob instead of relying
on Python `repr`), `Adding max-iterations` (the `max_turns = 20` guard),
`Fix API key calling` / `Fix leak of settings` (test cleanups). This shows
active, fast iteration toward correctness right after the merge — worth
factoring into how much further polish is actually still needed (see below,
much of the "obvious" stuff is already done).

## Integration pass — structural fixes applied (2026-06-08)

Five of the ten gaps from the original review were structural (not blocked
on Phase 3/4) and have now been fixed directly on `main`:

1. **Model id bumped to the locked stack id.** `AgentController` and
   `Reflector` now both default to `model: str = "claude-sonnet-4-6"`,
   matching CLAUDE.md §2 and `EmailDrafter`. *(Resolves Gap #1.)*
2. **`controller.py.bak` deleted.** Stray 102-line backup removed from git.
   *(Resolves Gap #2.)*
3. **`ingest_awards` no longer does a lossy days→months conversion.** The
   tool schema now asks the model for `months_back` directly (matching
   `backfill_awards()`'s actual unit), so "check today" can no longer
   silently turn into a live 1-month TED back-fill. *(Resolves Gap #4.)*
4. **Real dry-run/sandbox mode added.** `AgentController.__init__` gained
   `dry_run: bool = True` (safe by default) and `max_turns: int = 20`
   (now configurable rather than a magic number). `dry_run` is threaded all
   the way through `dispatch_tool(..., dry_run=...)` into
   `poll_contract_notices`, `backfill_awards`, and `download_dossiers` —
   the exact functions that already supported a `dry_run` kwarg, just never
   received it from the agent. Wired end-to-end:
   - `POST /api/v1/agent/run` now accepts an optional `dry_run` field
     (`AgentRequest.dry_run: bool = True`) and forwards it to the
     controller.
   - `agent_smoke.py --live` now actually flips `dry_run=False` (previously
     a cosmetic flag the script's own comment admitted didn't gate
     anything); without `--live` the script reports what *would* happen.
   - `scripts/README.md` documents the new `--live`/`dry_run` contract for
     `agent_smoke.py`, mirroring the established `ted_smoke.py`/
     `awards_smoke.py` convention, plus an explicit safety note that a
     casual chat goal can otherwise *plan* a live ingestion as a side
     effect.
   *(Resolves Gap #5.)*
5. **`max_turns` exceeded no longer crashes the request.** Replaced
   `raise RuntimeError(...)` with graceful truncation: the loop stops,
   returns the partial `steps`/`output` plus `truncated: true` and a
   human-readable "[Agent stopped after N turns ...]" prefix on the output,
   and still persists the (partial) run to `agent_runs` — useful input for
   the reflection loop rather than a lost 500. `AgentResponse` gained a
   `truncated: bool = False` field so the API surfaces this distinctly from
   a clean finish. *(Resolves Gap #6.)*

**Tests**: added 3 new cases to `test_controller.py` —
`test_agent_controller_defaults_to_dry_run` (constructor defaults to
`dry_run=True` and forwards it to `dispatch_tool`),
`test_agent_controller_forwards_explicit_live_mode` (`dry_run=False` is
forwarded unchanged), and
`test_agent_controller_truncates_gracefully_after_max_turns` (an
`EndlessToolUseClient` that never reaches `end_turn` is stopped at
`max_turns=3`, returns `truncated=True` + 3 logged steps, raises nothing,
and still commits the run). All 5 agent tests pass
(`pytest tests/agent -v`); full suite run gave 55 passed / 7 errors, the
errors being pre-existing `gtm_test` Postgres connection failures in
`test_dossier_downloader.py` (Docker Desktop wasn't running) — unrelated to
this pass.

## What works well

- **File layout matches our own plan almost exactly** — `controller.py`
  (loop) / `tools.py` (schemas+dispatch) / `reflector.py` (reflection),
  i.e. the "2-3 files" `docs/Notes.md` called for.
- **`AgentRun` persistence** gives the reflection loop something concrete
  to feed on, and doubles as a debugging/demo-narration trail ("what did
  the agent do yesterday").
- **`query_db` guardrails show the right instinct** (read-only, blocklist,
  row cap) even if the implementation is still a blunt instrument (#7).
- **Tool → backend wiring is correct in spirit**: each tool maps to a real
  function we already have (`poll_contract_notices`, `backfill_awards`,
  `download_dossiers`, `MatchingPipeline`, `EmailDrafter`) rather than
  inventing a parallel code path.
- **`agent_smoke.py` follows the team's established conventions** (same
  shape as `ted_smoke.py`/`awards_smoke.py`, documented in
  `scripts/README.md`).
- 5/5 agent tests pass locally (2 original + 3 added in the integration
  pass — fully mocked, see Remaining gap #9 for the caveat that still
  applies).

## Gaps — original findings (struck through where now resolved)

This is the original gap list from the first review pass, kept intact for
the historical "why" behind each fix. Resolved items are struck through and
point at the Integration-pass entry that fixed them; unresolved items are
carried forward verbatim into **Remaining gaps** below.

1. ~~**Model id is stale relative to our locked stack.** Both
   `AgentController` and `Reflector` default to
   `model: str = "claude-3-5-sonnet-20241022"`. CLAUDE.md §2 pins
   **`claude-sonnet-4-6`** as the project's locked model id (and
   `EmailDrafter` in `generation/drafter.py` already defaults to it
   correctly). This should be made consistent — and `claude-3-5-sonnet-...`
   dated IDs are the kind of thing that quietly stop working as Anthropic
   retires older snapshots.~~ **Fixed — Integration pass #1.**
2. ~~**`controller.py.bak` is checked into git** — a stray backup from the
   `a7b4600` refactor (102 lines, near-duplicate of the old controller).
   Pure dead weight; should be deleted.~~ **Fixed — Integration pass #2.**
3. **The agent's two most interesting tools point at stubs.**
   `find_matches` calls `MatchingPipeline().run(tender_id)`, which is
   `def run(...): ...` (Ellipsis, returns `None`) — `len(matches)` then
   raises `TypeError`, swallowed by the `except` and surfaced to the LLM as
   `"Error finding matches: object of type 'NoneType' has no len()"`.
   `draft_email` hits the same wall via `EmailDrafter().draft()`. **The
   agent layer is built and tested against an interface that doesn't exist
   yet** — Phase 3 (`app/matching/*`) and Phase 4 (`generation/drafter.py`)
   need to land before these two tools produce anything beyond an error
   string the LLM has to explain away. This is the single biggest blocker
   to a convincing demo of the agent ("find me matches for tender X and
   draft an email" currently always fails at step 2).
4. ~~**`ingest_awards`'s `days_back → months` conversion is lossy and
   surprising.** `months = max(1, days // 30)` means `days_back=1` (an
   agent saying "check today") silently becomes a 1-*month* TED back-fill —
   a much larger live API pull / DB write than the user's phrasing implies.
   Either expose `months` directly in the tool schema for awards, or give
   `backfill_awards` a days-based entry point.~~ **Fixed — Integration pass
   #3** (schema now asks for `months_back` directly; no conversion to get
   wrong).
5. ~~**No real dry-run/sandbox mode for write-capable tools.**
   `ingest_tenders` / `ingest_awards` / `download_dossiers` are always
   invoked with `dry_run=False`. `agent_smoke.py`'s own `--live` flag is
   acknowledged in its source comment as not actually gating anything yet
   ("currently to actually prevent DB modifications from tools, we'd need
   to mock the tools..."). Practically: a user just *chatting* with the
   agent ("find me a German tender") can cause the LLM to plan a live TED
   poll, a live dossier download sweep, and DB writes as side effects —
   with no confirmation step. Worth adding a real read-only/sandbox
   controller mode before any public-facing demo.~~ **Fixed — Integration
   pass #4** (`AgentController(dry_run=True)` by default, threaded through
   `dispatch_tool` into all three write-capable functions; `--live` /
   `dry_run` request field actually gate it now).
6. ~~**`max_turns` exceeded raises `RuntimeError`**, which propagates through
   `dispatch_tool`/`AgentController.run` straight into a `500` from the
   `/run` endpoint — losing whatever partial plan/steps were already
   executed. Better: return the partial `steps`/`output` plus a
   `"ran out of turns"` note, so a long plan degrades gracefully instead of
   crashing the request.~~ **Fixed — Integration pass #5** (graceful
   truncation with `truncated: true`, partial results preserved and
   persisted).
7. **`query_db`'s safety check is a naive substring blocklist**, not a real
   SQL-safety mechanism. E.g. a query selecting the `documents.downloaded_at`
   or any `updated_at` column would trip the `"update"` substring check; a
   `WHERE comment LIKE '%insert%'` would too. It also still executes the
   full query server-side before truncating to 50 rows via `fetchmany` —
   fine at our current data volume (a handful of rows per table) but not a
   real safety limit. A read-only DB role, or a proper SQL parser
   (`sqlglot`) checking statement type, would be more robust long-term —
   not urgent at this scale, but worth a comment/TODO so it isn't mistaken
   for a real security boundary.
8. **The reflection loop is built but not wired into anything.**
   `reflector.py` is a standalone script with a `__main__` block — no
   APScheduler hook (Job 4 is still pending), no API endpoint, and nothing
   reads its output back into `lr_weights.py` (still a stub). The
   "self-improvement" angle `docs/Notes.md` flagged as a jury-pleaser is
   currently just "the agent can narrate what it did," not "the agent
   changes its own behavior based on that narration."
9. **Tests are fully mocked end-to-end.** `MockClient`/`MockMessages`
   stand in for `anthropic.Anthropic`; `dispatch_tool` and `SessionLocal`
   are patched. They correctly validate the loop's control flow and the
   DB-save call, but never exercise a real Anthropic call, the real tool
   dispatch against a live/staging DB, or the actual tool schemas against
   Anthropic's strict validation. `agent_smoke.py` and
   `test_anthropic_schema.py` (an ad-hoc script, not a pytest test) are the
   only paths that touch the real API — neither runs in CI. Worth at least
   a CI-skippable "live" test class gated behind `ANTHROPIC_API_KEY`
   presence, the way `ted_smoke.py --live` is gated.
10. **Response model loses type information.** `AgentStep.args:
    dict[str, Any]` flattens whatever typed value the LLM provided (e.g.
    `tender_id` is declared `integer` in the tool schema, but comes back as
    an untyped dict entry in the API response) — fine for a debug view, but
    worth keeping in mind if the frontend ever needs to act on `steps`
    programmatically rather than just display them.

## Remaining gaps — what's still needed for full functionality

Renumbered from the original list — items #1, #2, #4, #5, #6 above are
done (see Integration pass). What's left:

1. **The agent's two most interesting tools still point at stubs.**
   `find_matches` calls `MatchingPipeline().run(tender_id)`, which is
   `def run(...): ...` (Ellipsis, returns `None`) — `len(matches)` then
   raises `TypeError`, swallowed by the `except` and surfaced to the LLM as
   `"Error finding matches: object of type 'NoneType' has no len()"`.
   `draft_email` hits the same wall via `EmailDrafter().draft()`. **This is
   still the single biggest blocker** to a convincing agent demo — no
   amount of controller-level polish changes that "find me matches for
   tender X and draft an email" fails at step 2 until Phase 3
   (`app/matching/*`) and Phase 4 (`generation/drafter.py`) land. Nothing
   in this integration pass touched this on purpose — it's a sequencing
   problem, not a structural one, and the fix is "build the matching
   pipeline / drafter," not "patch the agent."
2. **`query_db`'s safety check is a naive substring blocklist**, not a real
   SQL-safety mechanism. E.g. a query selecting the `documents.downloaded_at`
   or any `updated_at` column would trip the `"update"` substring check; a
   `WHERE comment LIKE '%insert%'` would too. It also still executes the
   full query server-side before truncating to 50 rows via `fetchmany` —
   fine at our current data volume (a handful of rows per table) but not a
   real safety limit. A read-only DB role, or a proper SQL parser
   (`sqlglot`) checking statement type, would be more robust long-term —
   not urgent at this scale, but worth a comment/TODO so it isn't mistaken
   for a real security boundary. *(Not changed in this pass — judged lower
   priority than the dry-run/max-turns fixes, which gate actual writes
   rather than just reads.)*
3. **The reflection loop is built but not wired into anything.**
   `reflector.py` is a standalone script with a `__main__` block — no
   APScheduler hook (Job 4 is still pending), no API endpoint, and nothing
   reads its output back into `lr_weights.py` (still a stub). The
   "self-improvement" angle `docs/Notes.md` flagged as a jury-pleaser is
   currently just "the agent can narrate what it did," not "the agent
   changes its own behavior based on that narration." Wiring this in is
   naturally sequenced *after* Job 4 (APScheduler) and Phase 5 (feedback +
   LR retraining), both still pending.
4. **Tests are fully mocked end-to-end.** `MockClient`/`MockMessages` (and
   the new `EndlessToolUseClient`) stand in for `anthropic.Anthropic`;
   `dispatch_tool` and `SessionLocal` are patched. They correctly validate
   the loop's control flow, the dry-run/max-turns plumbing, and the
   DB-save call — but never exercise a real Anthropic call, the real tool
   dispatch against a live/staging DB, or the actual tool schemas against
   Anthropic's strict validation. `agent_smoke.py` and
   `test_anthropic_schema.py` (an ad-hoc script, not a pytest test) are the
   only paths that touch the real API — neither runs in CI. Worth at least
   a CI-skippable "live" test class gated behind `ANTHROPIC_API_KEY`
   presence, the way `ted_smoke.py --live` is gated.
5. **Response model loses type information.** `AgentStep.args:
   dict[str, Any]` flattens whatever typed value the LLM provided (e.g.
   `tender_id` is declared `integer` in the tool schema, but comes back as
   an untyped dict entry in the API response) — fine for a debug view, but
   worth keeping in mind if the frontend ever needs to act on `steps`
   programmatically rather than just display them.

## Suggested next step

The structural/safety layer is now solid: locked model id, no stray files,
accurate tool semantics, a real dry-run default, and graceful degradation
on long plans — all verified by passing tests. The **remaining blocker is
purely sequencing**: `find_matches` and `draft_email` are dead ends until
Phase 3/4 land. The productive path now is to implement
`app/matching/pipeline.py` + `generation/drafter.py` (using the
`easy_demo` port as a starting point — see
[branch_review_easy_demo.md](branch_review_easy_demo.md)) so the agent's
two most interesting tools have something real to call. Once that's in,
revisit Remaining gaps #2–#5 (SQL guardrails, reflection-loop wiring,
live-API test coverage, typed step args) as polish passes — none of them
block a working demo the way the matching/drafting stubs currently do.
