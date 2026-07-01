"""Agent Controller — Claude tool-use orchestrator (streaming + resumable).

The controller drives a Claude planner-executor loop and yields **SSE events**
(`status` / `step` / `awaiting_input` / `final` / `error`) so the UI shows live
progress instead of a frozen spinner. The conversation is persisted to
`agent_sessions`, so a run that pauses on `ask_user` (tender disambiguation) can
be resumed with the user's choice via `stream_continue`.

Guardrails (G22): the matching/ranking is 100% the deterministic pipeline — the
LLM only *chooses* tools and narrates. The live-network tools are caged in
`tools.dispatch_tool` (no network in dry-run; bounded + at-most-once live;
`ingest_awards` gated on a zero-result `find_matches`). The per-run guard state
lives in `agent_sessions.run_state` so it survives a pause/resume.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import anthropic
from sqlalchemy.orm.attributes import flag_modified

from app.agent import progress
from app.agent.tools import AGENT_TOOLS, dispatch_tool
from app.db.models import AgentRun, AgentSession

SCHEMA_REFERENCE = """DATABASE SCHEMA (for the `query_db` tool — PostgreSQL).

Use `query_db` for questions the purpose-built tools do NOT cover — e.g. aggregations,
rankings, or history across many tenders/awards/companies ("which buyers awarded the
most contracts", "top companies by total contract value", "how many tenders per
country"). `query_db` accepts ONE read-only `SELECT` statement (no `;` chaining, no
writes), and returns at most 50 rows — always add an explicit `ORDER BY` + `LIMIT`.

Tables and their key columns:

- tenders (procurement notices; PK `id` int)
    id, ted_notice_id (public TED id, text), title, description, buyer_name,
    buyer_country (alpha-3, e.g. 'DEU'), cpv_codes (JSONB array of text),
    deadline (timestamptz), budget_eur (float, often NULL), currency, status,
    is_restricted (bool), tender_profile (JSONB, NULL until extracted), ingested_at.

- awards (past TED contract-award notices — the source of the supplier pool; PK `id` int)
    id, ted_notice_id, cpv_code, notice_title, description, procedure_type, nuts_code,
    buyer_name, buyer_country, winner_raw_name (as printed on the notice),
    winner_identifier (tax id), winner_country, winner_canonical_id (FK -> companies.id,
    NULLABLE), contract_value_eur (float), contract_currency, award_date (date),
    n_offers_received (int). NO FK to tenders (awards and tenders are separate TED
    publications).

- companies (canonical legal entities resolved from award winners; PK `id` int)
    id, canonical_name, resolution_key, registration_id (tax id), aliases (JSON), country.

- company_profiles (the MATCHABLE supplier pool, with embeddings; PK `id` uuid)
    id, name, country, website, capabilities (JSONB), certifications (JSONB),
    source_company_id (FK -> companies.id).

- matches (pipeline output; PK `id` uuid)
    id, tender_id (FK -> tenders.id), company_id (FK -> company_profiles.id),
    semantic_score, budget_score, location_score, qualification_score, final_score,
    is_disqualified (bool), weights (JSONB), explanation.

- emails (PK `id` uuid): id, match_id (FK -> matches.id), recipient_type
    ('supplier'|'buyer'), tender_id, subject, body, status, sent_at.

- feedback (PK `id` uuid): id, match_id (FK -> matches.id, nullable), rating (smallint,
    +1 / -1), comment.

Query gotchas — respect these or the answer will be wrong:
- To rank/aggregate WINNERS as entities, group by `awards.winner_canonical_id` (and join
  `companies` for the name), NOT by `winner_raw_name` (spelling varies) — but note some
  awards have `winner_canonical_id IS NULL`.
- `awards.contract_value_eur` is NOT FX-converted despite its name — it is in
  `contract_currency`. Do not SUM across mixed currencies without filtering
  (e.g. `WHERE contract_currency = 'EUR'`), and treat `-1` / `0` as "not disclosed".
- `companies` (award winners) and `company_profiles` (matchable pool) are DIFFERENT
  tables — join via `company_profiles.source_company_id = companies.id` if you must bridge.
- `tenders.cpv_codes` is a JSONB array; use JSONB operators (e.g.
  `cpv_codes @> '["45000000"]'` or `jsonb_array_elements_text(cpv_codes)`).
"""

SYSTEM_PROMPT = (
    """You are the GTM Agent Orchestrator for a construction-tech B2B \
lead-generation tool.

Tenders (public procurement notices) and the supplier pool (companies that won past \
TED awards) are ALREADY ingested into our local database. Your primary job is to \
resolve the tender the user means, run the matching pipeline on it, and explain the \
result. You can ALSO answer analytical questions about the ingested data via `query_db`.

Plan (for the primary "match a tender" flow):
1. RESOLVE the tender with `find_tender` (accepts a numeric id or words from the title).
   - Exactly one match: use it.
   - Several matches: call `ask_user` with the candidates and STOP for the user to pick.
   - No match: if this is a live run you MAY call `ingest_tenders` ONCE, then
     `find_tender` again; otherwise tell the user it isn't in the database.
2. (Optional) `extract_tender_profile` if certification-aware matching is useful.
3. MATCH with `find_matches` (the deterministic embedding + trained-model pipeline).
   - If it returns zero matches, you MAY call `ingest_awards` ONCE (live runs only) to
     rebuild the pool, then re-run `find_matches`.
4. EXPLAIN the top suppliers, grounding every reason ONLY in the scores/evidence the
   pipeline returned. Optionally `draft_email` to the top match.

For OTHER questions (aggregations, rankings, history across the data) that the tools
above do not answer, use `query_db` against the schema below. If a request cannot be
answered with the available tools/data, say so plainly instead of guessing — do not
invent suppliers, numbers, or columns.

Rules:
- The data is LOCAL — never assume you must fetch from TED. Prefer the read-only tools.
- Do NOT call `ingest_tenders` / `ingest_awards` except as the explicit fallbacks above.
- Use `ask_user` whenever you are unsure which tender or option the user wants.
- Ground every factual claim in tool output — never fabricate scores, companies, or rows.
- Be concise. Think step by step, then act with tool calls.

"""
    + SCHEMA_REFERENCE
)

ANTHROPIC_TOOLS = [
    {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": tool["input_schema"],
    }
    for tool in AGENT_TOOLS
]


def _block_to_dict(block: Any) -> dict[str, Any]:
    """Convert an SDK content block to a JSON-serializable, API-valid dict.

    We store the conversation in JSONB and feed it back into `messages.create`,
    so the assistant turns must be plain dicts — not raw SDK objects."""
    btype = getattr(block, "type", None)
    if btype == "text":
        return {"type": "text", "text": block.text}
    if btype == "tool_use":
        inp = block.input if isinstance(block.input, dict) else {}
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": inp}
    return {"type": "text", "text": ""}


def _as_uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class AgentController:
    """Top-level orchestrator that turns user goals into tool calls."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
        dry_run: bool = True,
        max_turns: int = 20,
    ) -> None:
        if model is None:
            from app.core.config import get_settings

            model = get_settings().anthropic_model
        self.model = model
        # Client is injectable so tests drive the loop with a scripted fake and
        # never touch the network (same pattern as EmailDrafter).
        self.client = client or anthropic.Anthropic(api_key=api_key)
        # Safety default: the caged write tools no-op the network in dry-run.
        self.dry_run = dry_run
        self.max_turns = max_turns

    # ── public entry points (generators of SSE event dicts) ──────────────────

    def stream_run(self, goal: str) -> Iterator[dict[str, Any]]:
        """Start a fresh run for `goal`; yield SSE events until done or paused."""
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            sess = AgentSession(
                goal=goal,
                dry_run=self.dry_run,
                status="running",
                messages=[{"role": "user", "content": goal}],
                steps=[],
                run_state={},
            )
            db.add(sess)
            db.commit()
            yield {
                "type": "status",
                "message": "Reading your request…",
                "session_id": str(sess.id),
            }
            yield from self._drive(db, sess)

    def stream_continue(self, session_id: str, reply: str) -> Iterator[dict[str, Any]]:
        """Resume a paused (`awaiting_input`) run with the user's `reply`."""
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            try:
                sess = db.get(AgentSession, _as_uuid(session_id))
            except (ValueError, TypeError):
                sess = None
            if sess is None:
                yield {"type": "error", "message": f"Unknown agent session {session_id}."}
                return
            if sess.status != "awaiting_input":
                yield {
                    "type": "error",
                    "message": (
                        f"Session {session_id} is not awaiting input "
                        f"(status={sess.status})."
                    ),
                }
                return

            # Carry the run's mode across the pause so a live run stays live.
            self.dry_run = bool(sess.dry_run)

            messages = sess.messages or []
            pending = sess.pending or {}
            ask_id = pending.get("ask_id")

            # Answer the open ask_user tool_use, and stub any other tool_use blocks
            # in that same assistant turn (the API requires a result for every one).
            tool_results: list[dict[str, Any]] = []
            last = messages[-1] if messages else None
            if isinstance(last, dict) and last.get("role") == "assistant":
                for block in last.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        if block.get("id") == ask_id:
                            content = str(reply)
                        else:
                            content = (
                                "(deferred — the user was asked to clarify first; "
                                "call again if still needed)"
                            )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.get("id"),
                                "content": content,
                            }
                        )
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            else:
                # No structured pending tool — just feed the reply as a user turn.
                messages.append({"role": "user", "content": str(reply)})

            sess.messages = messages
            sess.pending = None
            sess.status = "running"
            self._persist(db, sess)
            yield {
                "type": "status",
                "message": "Got it — continuing…",
                "session_id": str(sess.id),
            }
            yield from self._drive(db, sess)

    def run(self, user_goal: str) -> dict[str, Any]:
        """Convenience: drain `stream_run` and return the last terminal event.

        Returns the `final`, `awaiting_input`, or `error` event dict. Handy for
        programmatic callers and tests (the SSE endpoints stream the events)."""
        last: dict[str, Any] = {
            "type": "final",
            "goal": user_goal,
            "steps": [],
            "output": "",
            "truncated": False,
        }
        for evt in self.stream_run(user_goal):
            if evt.get("type") in ("final", "awaiting_input", "error"):
                last = evt
        return last

    # ── the loop ─────────────────────────────────────────────────────────────

    def _drive(self, db: Any, sess: AgentSession) -> Iterator[dict[str, Any]]:
        """Drive the loop; on any unexpected failure mark the session `error`.

        The Anthropic call (and DB persistence) inside `_run_loop` can raise —
        without this the session row would be left `running` forever: a dangling
        state that `stream_continue` can't resume and that's indistinguishable
        from an in-flight run. We flip the status to `error` and surface an
        `error` event (the API layer's own guard is now a redundant backstop)."""
        try:
            yield from self._run_loop(db, sess)
        except Exception as e:  # noqa: BLE001 — surface as an event, don't leak `running`
            self._mark_error(db, sess)
            yield {
                "type": "error",
                "session_id": str(sess.id),
                "message": f"Agent execution failed: {e}",
            }

    def _run_loop(self, db: Any, sess: AgentSession) -> Iterator[dict[str, Any]]:
        messages: list[Any] = sess.messages if sess.messages is not None else []
        steps: list[Any] = sess.steps if sess.steps is not None else []
        run_state: dict[str, Any] = sess.run_state if sess.run_state is not None else {}

        final_output = ""
        truncated = False
        turns = 0

        while True:
            turns += 1
            if turns > self.max_turns:
                # Don't blow up the request — return partial progress with a note.
                truncated = True
                final_output = (
                    f"[Agent stopped after {self.max_turns} turns without reaching a "
                    "final answer. Partial progress above.]\n" + final_output
                )
                break

            yield {"type": "status", "message": progress.THINKING}
            response = self.client.messages.create(
                model=self.model,
                system=SYSTEM_PROMPT,
                max_tokens=4096,
                messages=messages,
                tools=ANTHROPIC_TOOLS,
            )
            messages.append(
                {"role": "assistant", "content": [_block_to_dict(b) for b in response.content]}
            )

            if response.stop_reason == "tool_use":
                # Human-in-the-loop pause: if the model asked the user something,
                # persist and stop here — resume happens via stream_continue.
                ask = next(
                    (
                        b
                        for b in response.content
                        if getattr(b, "type", None) == "tool_use" and b.name == "ask_user"
                    ),
                    None,
                )
                if ask is not None:
                    args = ask.input if isinstance(ask.input, dict) else {}
                    question = str(args.get("question") or "Which option do you want?")
                    options = args.get("options") or []
                    sess.pending = {"ask_id": ask.id, "question": question, "options": options}
                    sess.status = "awaiting_input"
                    self._sync(sess, messages, steps, run_state)
                    self._persist(db, sess)
                    yield {
                        "type": "awaiting_input",
                        "session_id": str(sess.id),
                        "question": question,
                        "options": options,
                    }
                    return

                tool_results = []
                for block in response.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    name = block.name
                    args = block.input if isinstance(block.input, dict) else {}
                    steps.append({"tool": name, "args": args})
                    yield {"type": "status", "message": progress.progress_message(name, args)}
                    yield {"type": "step", "tool": name, "args": args}
                    result_str = dispatch_tool(
                        name, args, db, dry_run=self.dry_run, run_state=run_state
                    )
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result_str}
                    )

                messages.append({"role": "user", "content": tool_results})
                sess.status = "running"
                self._sync(sess, messages, steps, run_state)
                self._persist(db, sess)
            else:
                for block in response.content:
                    if getattr(block, "type", None) == "text":
                        final_output += block.text
                break

        yield {"type": "status", "message": progress.FINALIZING}
        sess.status = "done"
        self._sync(sess, messages, steps, run_state)
        self._persist(db, sess)
        # Persist the completed run for the reflection loop (incl. truncated ones).
        db.add(AgentRun(goal=sess.goal, steps=steps, output=final_output))
        db.commit()
        yield {
            "type": "final",
            "session_id": str(sess.id),
            "goal": sess.goal,
            "steps": steps,
            "output": final_output,
            "truncated": truncated,
        }

    # ── persistence helpers ──────────────────────────────────────────────────

    @staticmethod
    def _sync(
        sess: AgentSession,
        messages: list[Any],
        steps: list[Any],
        run_state: dict[str, Any],
    ) -> None:
        sess.messages = messages
        sess.steps = steps
        sess.run_state = run_state

    @staticmethod
    def _mark_error(db: Any, sess: AgentSession) -> None:
        """Best-effort flip of a failed run to `error`.

        Roll back any poisoned transaction first (the failure may have been a
        DB error mid-commit), then persist just the status. Both steps are
        guarded so this never itself raises out of the `_drive` except handler."""
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        try:
            sess.status = "error"
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()

    @staticmethod
    def _persist(db: Any, sess: AgentSession) -> None:
        # The JSON list/dict columns we append to in place aren't auto-detected as
        # dirty — flag them (only if loaded into the instance state). `pending` /
        # `status` / `dry_run` are always *reassigned*, so normal change detection
        # covers them and they must not be force-flagged here (raises if unloaded).
        for attr in ("messages", "steps", "run_state"):
            if attr in sess.__dict__:
                flag_modified(sess, attr)
        db.commit()
