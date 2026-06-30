"""Offline guardrail tests for the streaming/resumable AgentController (G22).

The Anthropic client is a scripted fake (no network), and the live-ingest
functions are monkeypatched so we can assert they are NOT called in dry-run and
are bounded/gated when live. DB-backed (agent_sessions) via the `db_session`
fixture, like the reflector tests. No ML deps (find_matches is faked).
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from app.agent.controller import AgentController
from app.db.models import AgentSession

# ── scripted fake Anthropic client ───────────────────────────────────────────

def _msg(blocks, stop_reason):
    return Message(
        id="msg_" + uuid.uuid4().hex[:6],
        content=blocks,
        model="claude-test",
        role="assistant",
        stop_reason=stop_reason,
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _tool(name, inp, block_id="tool_1"):
    return _msg([ToolUseBlock(id=block_id, name=name, input=inp, type="tool_use")], "tool_use")


def _final(text):
    return _msg([TextBlock(text=text, type="text")], "end_turn")


class _ScriptedMessages:
    def __init__(self, scripts):
        self.scripts = scripts
        self.calls = 0

    def create(self, *args, **kwargs):
        i = min(self.calls, len(self.scripts) - 1)
        self.calls += 1
        return self.scripts[i]


class _ScriptedClient:
    def __init__(self, scripts):
        self.messages = _ScriptedMessages(scripts)


class _FakePipelineZero:
    """MatchingPipeline stub that returns no matches (no embedder/torch)."""

    def __init__(self, *args, **kwargs):
        pass

    def run(self, *args, **kwargs):
        return []


# ── tests ────────────────────────────────────────────────────────────────────

def test_dry_run_ingest_makes_no_network(db_session, monkeypatch):
    """A dry-run ingest_tenders must NOT call the live TED poll — the old bug
    was that dry-run still hit the network."""
    poll = MagicMock()
    monkeypatch.setattr("app.ingestion.ted_client.poll_contract_notices", poll)

    client = _ScriptedClient([
        _tool("ingest_tenders", {"days_back": 3}),
        _final("Nothing ingested — this was a dry run."),
    ])
    agent = AgentController(client=client, dry_run=True)
    result = agent.run("Get the latest tenders")

    poll.assert_not_called()
    assert result["type"] == "final"
    assert result["steps"][0]["tool"] == "ingest_tenders"


def test_ingest_tenders_capped_once_live(db_session, monkeypatch):
    """Live ingest_tenders runs at most once per run, even if the model asks twice."""
    poll = MagicMock(return_value={"fetched": 0, "new": 0, "updated": 0, "errors": 0})
    monkeypatch.setattr("app.ingestion.ted_client.poll_contract_notices", poll)

    client = _ScriptedClient([
        _tool("ingest_tenders", {"days_back": 2}, block_id="a"),
        _tool("ingest_tenders", {"days_back": 2}, block_id="b"),
        _final("Done."),
    ])
    agent = AgentController(client=client, dry_run=False)
    agent.run("Ingest tenders twice")

    assert poll.call_count == 1


def test_ingest_awards_gated_then_allowed_after_zero_match(db_session, monkeypatch):
    """ingest_awards is refused until find_matches returns zero, then permitted once."""
    backfill = MagicMock(return_value={"new": 0})
    monkeypatch.setattr("app.ingestion.awards_client.backfill_awards", backfill)
    monkeypatch.setattr("app.matching.pipeline.MatchingPipeline", _FakePipelineZero)

    client = _ScriptedClient([
        _tool("find_matches", {"tender_id": 5}, block_id="m"),
        _tool("ingest_awards", {"months_back": 1}, block_id="aw"),
        _final("Rebuilt the pool."),
    ])
    agent = AgentController(client=client, dry_run=False)
    result = agent.run("Match tender 5, rebuild pool if empty")

    backfill.assert_called_once()
    tools = [s["tool"] for s in result["steps"]]
    assert tools == ["find_matches", "ingest_awards"]


def test_ingest_awards_refused_without_zero_match(db_session, monkeypatch):
    """Without a prior zero-result find_matches, ingest_awards must not run."""
    backfill = MagicMock(return_value={"new": 0})
    monkeypatch.setattr("app.ingestion.awards_client.backfill_awards", backfill)

    client = _ScriptedClient([
        _tool("ingest_awards", {"months_back": 1}),
        _final("Could not rebuild."),
    ])
    agent = AgentController(client=client, dry_run=False)
    agent.run("Rebuild the supplier pool")

    backfill.assert_not_called()


def test_ask_user_pauses_then_resumes(db_session):
    """ask_user pauses the run (awaiting_input + persisted session); a continue
    with the user's reply resumes the same conversation to completion."""
    run_client = _ScriptedClient([
        _tool(
            "ask_user",
            {"question": "Which tender?", "options": [{"id": "5", "label": "Tender 5"}]},
            block_id="ask",
        ),
    ])
    agent = AgentController(client=run_client, dry_run=True)
    paused = agent.run("Find suppliers for the school tender")

    assert paused["type"] == "awaiting_input"
    assert paused["question"] == "Which tender?"
    session_id = paused["session_id"]

    sess = db_session.get(AgentSession, uuid.UUID(session_id))
    assert sess is not None
    assert sess.status == "awaiting_input"
    assert sess.pending["ask_id"] == "ask"

    # Resume with a fresh controller (mirrors the /continue endpoint).
    resume_client = _ScriptedClient([_final("Resolved to tender 5 and ranked suppliers.")])
    resumer = AgentController(client=resume_client)
    events = list(resumer.stream_continue(session_id, "5"))

    final = next(e for e in events if e["type"] == "final")
    assert "Resolved to tender 5" in final["output"]

    db_session.expire_all()
    sess = db_session.get(AgentSession, uuid.UUID(session_id))
    assert sess.status == "done"


def test_max_turns_truncates_gracefully(db_session):
    """A plan that never finishes stops after max_turns with partial progress —
    it must not raise or loop forever (the credit-drain failure mode)."""
    client = _ScriptedClient([_tool("query_db", {"sql_query": "SELECT 1"})])  # endless
    agent = AgentController(client=client, dry_run=True, max_turns=3)
    result = agent.run("Loop forever")

    assert result["truncated"] is True
    assert "stopped after 3 turns" in result["output"]
    assert len(result["steps"]) == 3


def test_continue_unknown_session_errors(db_session):
    agent = AgentController(client=_ScriptedClient([_final("x")]))
    events = list(agent.stream_continue(str(uuid.uuid4()), "5"))
    assert events and events[-1]["type"] == "error"


def test_bad_query_db_does_not_poison_the_run(db_session):
    """A failing query_db (e.g. the model guessing a wrong table/column) must not
    abort the shared run transaction — the savepoint rolls it back and the run
    finishes normally. Regression for the live-smoke transaction-abort bug."""
    client = _ScriptedClient([
        _tool("query_db", {"sql_query": "SELECT * FROM nonexistent_table_xyz"}),
        _final("Recovered and finished."),
    ])
    agent = AgentController(client=client, dry_run=True)
    result = agent.run("Query a bad table then finish")

    assert result["type"] == "final"
    assert result["output"] == "Recovered and finished."
    assert [s["tool"] for s in result["steps"]] == ["query_db"]
