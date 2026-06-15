"""Tests for the agent tool dispatch layer — focused on the `query_db` guard.

The controller tests mock `dispatch_tool` entirely, so the read-only SQL guard
had no coverage. These exercise `_read_only_sql_error` directly (pure function)
plus one real-Postgres round-trip through `dispatch_tool` proving that a query
on `created_at` / `updated_at` columns now runs instead of being rejected by
the old substring blocklist.
"""
from __future__ import annotations

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
