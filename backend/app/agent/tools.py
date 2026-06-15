"""Agent Tools definition for the Anthropic tool-use loop.

This module defines the JSON schemas for the tools provided to Claude,
and the dispatch logic to call internal backend modules.
"""
from __future__ import annotations

import re

# Tools schema definitions for Anthropic API
AGENT_TOOLS = [
    {
        "name": "ingest_tenders",
        "description": "Fetch the latest renewable energy tenders from TED API.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days back to look for tenders.",
                    "default": 1
                }
            }
        }
    },
    {
        "name": "ingest_awards",
        "description": (
            "Back-fill historical contract award notices from TED to identify "
            "past tender winners. Looks back a number of months (the awards "
            "back-fill is month-granular, not day-granular)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "months_back": {
                    "type": "integer",
                    "description": "Number of months back to back-fill awards for.",
                    "default": 1
                }
            }
        }
    },
    {
        "name": "download_dossiers",
        "description": (
            "Attempt to download missing PDF dossiers/documents for all "
            "eligible tenders (bulk sweep)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "find_matches",
        "description": (
            "Run the matching pipeline for a given tender to find the top "
            "company matches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tender_id": {
                    "type": "integer",
                    "description": "The integer primary key of the tender (tenders.id)."
                },
                "top_n": {
                    "type": "integer",
                    "description": "Number of top matches to return.",
                    "default": 3
                }
            },
            "required": ["tender_id"]
        }
    },
    {
        "name": "draft_email",
        "description": "Draft an outreach email to the winning company based on a given match.",
        "input_schema": {
            "type": "object",
            "properties": {
                "match_id": {
                    "type": "string",
                    "description": "The UUID of the match."
                }
            },
            "required": ["match_id"]
        }
    },
    {
        "name": "query_db",
        "description": (
            "Run a read-only SQL query against the tracking database "
            "(e.g. 'SELECT * FROM tenders LIMIT 5')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql_query": {
                    "type": "string",
                    "description": "A valid PostgreSQL SELECT query."
                }
            },
            "required": ["sql_query"]
        }
    }
]

# Write / DDL verbs that must never run through the read-only `query_db` tool.
# Matched as whole words (\b) so legitimate identifiers like `created_at`,
# `updated_at`, or a `comment` column are NOT rejected. The previous guard used
# a plain substring check, which blocked every timestamp column on the PR #7
# tables (e.g. `SELECT created_at FROM tenders` tripped the `"create"` token).
# See docs/branch_review_agent_controller.md (query_db gap).
_FORBIDDEN_SQL_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create)\b",
    re.IGNORECASE,
)


def _read_only_sql_error(sql: str) -> str | None:
    """Return a human-readable reason if `sql` is not a safe read-only query.

    The primary gate is that the statement is a single `SELECT`; the keyword
    blocklist is defence-in-depth (a write would already have to get past the
    leading-SELECT and single-statement checks). Returns ``None`` when the
    query is acceptable.

    Note: a forbidden verb appearing inside a string literal (e.g.
    ``WHERE status = 'create'``) is still rejected — an accepted, rare
    trade-off for keeping the blocklist simple without a full SQL parser.
    """
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return "query was empty"
    if ";" in stripped:
        return "only a single statement is allowed"
    if not stripped.lower().startswith("select"):
        return "only SELECT queries are allowed"
    match = _FORBIDDEN_SQL_KEYWORDS.search(stripped)
    if match:
        return f"keyword '{match.group(0).lower()}' is not allowed in a read-only query"
    return None


def dispatch_tool(tool_name: str, tool_args: dict, session, dry_run: bool = True) -> str:
    """Dispatches the tool call to the actual backend logic.

    `dry_run` gates the write-capable tools (`ingest_tenders`,
    `ingest_awards`, `download_dossiers`): when True (the
    `AgentController` default) they validate inputs and report what
    *would* happen without hitting the live TED API or writing to the DB.
    Pass `dry_run=False` only for an explicitly "live" agent run.

    Returns the string representation of the tool output.
    """
    if tool_name == "query_db":
        from sqlalchemy import text

        sql = str(tool_args.get("sql_query", ""))
        reason = _read_only_sql_error(sql)
        if reason is not None:
            return f"Error executing query: {reason}."

        try:
            # Strip a trailing semicolon (allowed) and cap results so a large
            # table can't bloat the tool output fed back to the model.
            rows = session.execute(text(sql.strip().rstrip(";"))).mappings().fetchmany(50)
            return str([dict(row) for row in rows])
        except Exception as e:
            return f"Error executing query: {str(e)}"

    elif tool_name == "ingest_tenders":
        from app.core.config import get_settings
        from app.ingestion.ted_client import poll_contract_notices
        try:
            days = tool_args.get("days_back", 1)
            settings = get_settings()
            summary = poll_contract_notices(
                cpv_codes=settings.cpv_code_list,
                days=days,
                dry_run=dry_run
            )
            verb = "would be" if dry_run else "is"
            return f"Tender ingestion {verb} complete: {summary}"
        except Exception as e:
            return f"Error ingesting tenders: {str(e)}"

    elif tool_name == "ingest_awards":
        from app.core.config import get_settings
        from app.ingestion.awards_client import backfill_awards
        try:
            # The back-fill is month-granular — the tool schema asks the
            # model for months directly so "look back 1 day" can't silently
            # turn into a 1-month live pull (see docs/branch_review_agent_controller.md).
            months = max(1, int(tool_args.get("months_back", 1)))
            settings = get_settings()
            summary = backfill_awards(
                cpv_codes=settings.cpv_code_list,
                backfill_months=months,
                dry_run=dry_run
            )
            verb = "would be" if dry_run else "is"
            return f"Awards ingestion {verb} complete: {summary}"
        except Exception as e:
            return f"Error ingesting awards: {str(e)}"

    elif tool_name == "download_dossiers":
        from app.ingestion.dossier_downloader import download_dossiers
        try:
            # download_dossiers pulls all eligible tenders in bulk — there is
            # no per-tender filter on the underlying function.
            summary = download_dossiers(dry_run=dry_run)
            verb = "would be" if dry_run else "was"
            return f"Dossier download sweep {verb} triggered (run state: {summary})"
        except Exception as e:
            return f"Error downloading dossiers: {str(e)}"

    elif tool_name == "find_matches":
        try:
            # Backend matching modules are scaffolded but pipeline is defined
            from app.matching.pipeline import MatchingPipeline
            tender_id = tool_args["tender_id"]
            # top_n logic is usually handled inside or after run()
            pipeline = MatchingPipeline()
            # Requires pipeline.run to be fully implemented; the except below
            # catches the NotImplementedError the current stub raises.
            matches = pipeline.run(tender_id=tender_id)
            return f"Matching complete for tender {tender_id}. {len(matches)} matches found."
        except Exception as e:
            return f"Error finding matches: {str(e)}"

    elif tool_name == "draft_email":
        try:
            from app.generation.drafter import EmailDrafter
            match_id = tool_args["match_id"]
            # To draft properly, we should fetch evidence for the match_id from DB,
            # for now passing a mock or letting drafter handle it.
            drafter = EmailDrafter()
            result = drafter.draft(evidence={"match_id": match_id, "notes": "evidence goes here"})
            return f"Email generated successfully: {result}"
        except Exception as e:
            return f"Error drafting email: {str(e)}"

    return (
        f"Tool {tool_name} executed successfully with args: {tool_args} "
        "(Mocked response for layout)"
    )
