"""Tests for the agent tool dispatch layer — focused on the `query_db` guard.

The controller tests mock `dispatch_tool` entirely, so the read-only SQL guard
had no coverage. These exercise `_read_only_sql_error` directly (pure function)
plus one real-Postgres round-trip through `dispatch_tool` proving that a query
on `created_at` / `updated_at` columns now runs instead of being rejected by
the old substring blocklist.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agent.tools import _read_only_sql_error, dispatch_tool
from app.db.models import Company, Tender


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM tenders",
        "select id from tenders limit 5",
        # The regression: timestamp columns must not trip the create/update tokens.
        "SELECT created_at, updated_at FROM tenders",
        # A real column literally named `comment` (on the feedback table).
        "SELECT comment FROM feedback",
        # A trailing semicolon is allowed (single statement).
        "SELECT 1 FROM tenders;",
        "   SELECT 1   ",
    ],
)
def test_read_only_sql_accepts_valid_selects(sql: str) -> None:
    assert _read_only_sql_error(sql) is None


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO tenders (id) VALUES (1)",
        "UPDATE tenders SET title = 'x'",
        "DELETE FROM tenders",
        "DROP TABLE tenders",
        "ALTER TABLE tenders ADD COLUMN x int",
        "TRUNCATE tenders",
        "CREATE TABLE x (id int)",
        "SELECT 1; DROP TABLE tenders",  # multi-statement
        "WITH x AS (SELECT 1) SELECT * FROM x",  # not a leading SELECT
        "",
        "   ",
    ],
)
def test_read_only_sql_rejects_writes_and_multi_statements(sql: str) -> None:
    assert _read_only_sql_error(sql) is not None


@pytest.mark.parametrize(
    "sql",
    [
        # Superuser-reachable primitives a plain SELECT could otherwise run
        # (the app DB role is a Postgres superuser). P2.
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_read_binary_file('/etc/passwd')",
        "SELECT pg_ls_dir('/')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT pg_sleep(10)",
        "SELECT rolname, rolpassword FROM pg_authid",
        "SELECT * FROM pg_shadow",
        "SELECT dblink('host=evil', 'SELECT 1')",
        "SELECT set_config('x', 'y', false)",
        "SELECT pg_terminate_backend(1)",
        # Schema-qualified + case variants must still be caught.
        "SELECT pg_catalog.pg_read_file('x')",
        "select PG_SLEEP(1)",
    ],
)
def test_read_only_sql_rejects_dangerous_functions(sql: str) -> None:
    assert _read_only_sql_error(sql) is not None


def test_query_db_dispatch_blocks_dangerous_function() -> None:
    """The guard rejects a file-read SELECT before it ever touches the DB
    (MagicMock session proves no execution happens)."""
    out = dispatch_tool(
        "query_db", {"sql_query": "SELECT pg_read_file('/etc/passwd')"}, MagicMock()
    )
    assert "disallowed" in out.lower()


def test_query_db_runs_timestamp_columns_real_db(db_session) -> None:
    """End-to-end: SELECTs touching `created_at` (companies) and `updated_at`
    (tenders) must execute, not be rejected. These are the columns the old
    substring blocklist wrongly tripped on (`create` / `update`)."""
    db_session.add(
        Company(canonical_name="Query Guard GmbH", resolution_key="queryguard")
    )
    db_session.add(
        Tender(
            ted_notice_id="QDB-1",
            title="Query guard tender",
            cpv_codes=["45000000"],
            raw_json={"publication-number": "QDB-1"},
        )
    )
    db_session.flush()

    created = dispatch_tool(
        "query_db",
        {"sql_query": "SELECT canonical_name, created_at FROM companies"},
        db_session,
    )
    assert not created.startswith("Error executing query")
    assert "Query Guard GmbH" in created

    updated = dispatch_tool(
        "query_db",
        {"sql_query": "SELECT ted_notice_id, updated_at FROM tenders"},
        db_session,
    )
    assert not updated.startswith("Error executing query")
    assert "QDB-1" in updated


def test_query_db_blocks_write_real_db(db_session) -> None:
    """A write must be rejected before it ever reaches the database."""
    result = dispatch_tool(
        "query_db",
        {"sql_query": "DELETE FROM tenders"},
        db_session,
    )
    assert result.startswith("Error executing query")
    assert "SELECT" in result


# ── find_tender (local lookup) ───────────────────────────────────────────────

def _make_tender(ted_id: str, title: str, country: str = "DEU") -> Tender:
    return Tender(
        ted_notice_id=ted_id,
        title=title,
        buyer_country=country,
        cpv_codes=["45000000"],
        raw_json={"publication-number": ted_id},
    )


def test_find_tender_by_id(db_session) -> None:
    t = _make_tender("FT-1", "Ilmenau school new build")
    db_session.add(t)
    db_session.flush()

    out = dispatch_tool("find_tender", {"query": str(t.id)}, db_session)
    assert "Found 1 tender" in out
    assert f"id={t.id}" in out


def test_find_tender_by_ted_notice_id(db_session) -> None:
    """The public TED notice id (what the UI shows) must resolve a tender."""
    db_session.add(_make_tender("420398-2026", "Spain – Facilities management – CITRAM"))
    db_session.flush()

    out = dispatch_tool("find_tender", {"query": "420398-2026"}, db_session)
    assert "Found 1 tender" in out
    assert "TED 420398-2026" in out


def test_find_tender_by_title_single(db_session) -> None:
    db_session.add(_make_tender("FT-2", "Bridge refurbishment in Bremen"))
    db_session.flush()

    out = dispatch_tool("find_tender", {"query": "Bremen"}, db_session)
    assert "Found 1 tender" in out
    assert "Bridge refurbishment" in out


def test_find_tender_multiple_prompts_ask_user(db_session) -> None:
    db_session.add(_make_tender("FT-3", "School roof works Hamburg"))
    db_session.add(_make_tender("FT-4", "School heating works Hamburg"))
    db_session.flush()

    out = dispatch_tool("find_tender", {"query": "School"}, db_session)
    assert "Found 2 possible tenders" in out
    assert "ask_user" in out


def test_find_tender_none(db_session) -> None:
    out = dispatch_tool("find_tender", {"query": "nonexistent-xyz"}, db_session)
    assert "No tenders in the local database match" in out


# ── caged live-ingest tools ──────────────────────────────────────────────────

def test_ingest_tenders_dry_run_no_network(monkeypatch) -> None:
    poll = MagicMock()
    monkeypatch.setattr("app.ingestion.ted_client.poll_contract_notices", poll)

    out = dispatch_tool("ingest_tenders", {"days_back": 3}, None, dry_run=True, run_state={})
    assert "[dry-run]" in out
    poll.assert_not_called()


def test_ingest_tenders_live_capped_once(monkeypatch) -> None:
    poll = MagicMock(return_value={"fetched": 0})
    monkeypatch.setattr("app.ingestion.ted_client.poll_contract_notices", poll)

    state: dict = {}
    first = dispatch_tool("ingest_tenders", {"days_back": 2}, None, dry_run=False, run_state=state)
    second = dispatch_tool("ingest_tenders", {"days_back": 2}, None, dry_run=False, run_state=state)

    assert poll.call_count == 1
    assert "complete" in first
    assert "Already ingested" in second


def test_ingest_awards_refused_without_zero_match(monkeypatch) -> None:
    backfill = MagicMock()
    monkeypatch.setattr("app.ingestion.awards_client.backfill_awards", backfill)

    out = dispatch_tool("ingest_awards", {"months_back": 1}, None, dry_run=False, run_state={})
    assert "refused" in out
    backfill.assert_not_called()


def test_ingest_awards_allowed_after_zero_match(monkeypatch) -> None:
    backfill = MagicMock(return_value={"new": 0})
    monkeypatch.setattr("app.ingestion.awards_client.backfill_awards", backfill)

    out = dispatch_tool(
        "ingest_awards", {"months_back": 1}, None, dry_run=False, run_state={"zero_match": True}
    )
    assert "complete" in out
    backfill.assert_called_once()


def test_download_dossiers_disabled() -> None:
    out = dispatch_tool("download_dossiers", {}, None)
    assert "disabled" in out
