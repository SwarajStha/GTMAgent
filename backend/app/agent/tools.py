"""Agent tool definitions + dispatch for the Anthropic tool-use loop.

The agent is **DB-first**: tenders and the supplier pool (past TED-award winners)
are already ingested locally, so the default path is
``find_tender → find_matches → explain``, all read from the database. The two
live-network tools are **caged fallbacks** (see `dispatch_tool`):

* in dry-run they make **no network call** at all — they report what they *would*
  do (the old behaviour leaked: dry-run still hit live TED / portals);
* live, they are bounded and run **at most once per run**, and `ingest_awards`
  additionally only runs after a zero-result `find_matches`.

`download_dossiers` was **removed** from the agent surface: PDF portal scraping is
out of scope (G24), and its bulk sweep GET-ed every portal URL, wedging the
request. `find_tender` (local lookup) and `ask_user` (human-in-the-loop pause)
are new.
"""
from __future__ import annotations

import re

# Bounds on the caged live-ingest fallbacks so even a live run can't trigger a
# long unbounded poll / sweep (the demo-killer was an unbounded dossier sweep).
_INGEST_TENDERS_MAX_DAYS = 14
_INGEST_TENDERS_LIMIT = 200
_INGEST_AWARDS_MAX_MONTHS = 1
_FIND_TENDER_LIMIT = 8

# Tools schema definitions for the Anthropic API.
AGENT_TOOLS = [
    {
        "name": "find_tender",
        "description": (
            "Look up tenders ALREADY in the local database by id or by title "
            "text. Use this FIRST to resolve whichever tender the user means. "
            "Accepts a numeric id (e.g. '16') or words from the title (e.g. "
            "'Ilmenau school'). Returns up to 8 candidates with id, title, "
            "country and deadline. Never hits the network."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A tender id, or words from its title.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_matches",
        "description": (
            "Run the matching pipeline (semantic embedding + trained model) for "
            "a tender to rank the top company matches from the local supplier "
            "pool. Resolve the tender with find_tender first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tender_id": {
                    "type": "integer",
                    "description": "The integer primary key of the tender (tenders.id).",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Number of top matches to return.",
                    "default": 3,
                },
            },
            "required": ["tender_id"],
        },
    },
    {
        "name": "extract_tender_profile",
        "description": (
            "Run the Understanding layer on a tender: extract a structured "
            "profile (summary, required certifications, required capabilities, "
            "keywords) from its text and store it. The extracted certifications "
            "drive the matcher's certification gate. Optional — run before "
            "find_matches only when certification-aware matching is wanted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tender_id": {
                    "type": "integer",
                    "description": "The integer primary key of the tender (tenders.id).",
                }
            },
            "required": ["tender_id"],
        },
    },
    {
        "name": "draft_email",
        "description": "Draft an outreach email to the matched company for a given match.",
        "input_schema": {
            "type": "object",
            "properties": {
                "match_id": {
                    "type": "string",
                    "description": "The UUID of the match.",
                }
            },
            "required": ["match_id"],
        },
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
                    "description": "A valid PostgreSQL SELECT query.",
                }
            },
            "required": ["sql_query"],
        },
    },
    {
        "name": "ask_user",
        "description": (
            "Ask the human a clarifying question and PAUSE the run until they "
            "answer. Use this when find_tender returns more than one possible "
            "tender, or when you genuinely cannot proceed without a choice. "
            "Provide the candidate options so the user can pick one. Call it "
            "alone (no other tool in the same turn)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to show the user.",
                },
                "options": {
                    "type": "array",
                    "description": "Choices to present; each should have an 'id' and a 'label'.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "ingest_tenders",
        "description": (
            "FALLBACK ONLY. Fetch recent construction/IT tenders from the live "
            "TED API and upsert them locally. Use ONLY if find_tender finds "
            "nothing AND this is a live (non-dry-run) run. The tender pool is "
            "normally already ingested, so prefer find_tender. Bounded; runs at "
            "most once per run."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days back to look for tenders.",
                    "default": 1,
                }
            },
        },
    },
    {
        "name": "ingest_awards",
        "description": (
            "FALLBACK ONLY. Back-fill historical TED award notices to rebuild "
            "the supplier pool. Permitted ONLY after find_matches has returned "
            "zero matches for a tender, and only on a live run. It does NOT "
            "contain tenders — never use it to find a tender."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "months_back": {
                    "type": "integer",
                    "description": "Number of months back to back-fill awards for.",
                    "default": 1,
                }
            },
        },
    },
]

# Write / DDL verbs that must never run through the read-only `query_db` tool.
# Matched as whole words (\b) so legitimate identifiers like `created_at`,
# `updated_at`, or a `comment` column are NOT rejected. The previous guard used
# a plain substring check, which blocked every timestamp column on the PR #7
# tables (e.g. `SELECT created_at FROM tenders` tripped the `"create"` token).
# See docs/integration_gap_tracker.md (R6).
_FORBIDDEN_SQL_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke)\b",
    re.IGNORECASE,
)

# Superuser-reachable primitives that a *read-only* SELECT can still invoke
# (the app DB role is a Postgres superuser). Without this a single valid SELECT
# could read arbitrary files (`pg_read_file('/etc/passwd')`), dump password
# hashes (`pg_authid`/`pg_shadow`), reach other databases (`dblink`), stall the
# connection (`pg_sleep`), or kill backends — none of which the agent needs.
# Whole-word + case-insensitive, so `pg_catalog.pg_read_file` and quoted/upper
# variants are still caught. This is defence-in-depth at the app layer; the
# durable structural fix is running query_db under a least-privilege read-only
# role (see backend/scripts/README.md / the P2 plan). `pg_sleep` DoS is *also*
# bounded by the statement_timeout applied at execution.
_DANGEROUS_SQL_TOKENS = re.compile(
    r"\b("
    r"pg_read_file|pg_read_binary_file|pg_stat_file|"
    r"pg_ls_dir|pg_ls_logdir|pg_ls_waldir|pg_ls_tmpdir|pg_ls_archive_statusdir|"
    r"lo_import|lo_export|lo_get|lo_put|"
    r"pg_sleep|pg_sleep_for|pg_sleep_until|"
    r"pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|"
    r"set_config|"
    r"dblink|dblink_exec|"
    r"pg_authid|pg_shadow|pg_hba_file_rules|"
    r"pg_read_server_files|pg_write_server_files|pg_execute_server_program"
    r")\b",
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
    dangerous = _DANGEROUS_SQL_TOKENS.search(stripped)
    if dangerous:
        return (
            f"'{dangerous.group(0).lower()}' is a disallowed function/table "
            "(file access, credentials, cross-database, or sleep) in a read-only query"
        )
    return None


def _run_query_readonly(engine, sql: str, timeout_ms: int) -> str:
    """Execute `sql` on the least-privilege read-only engine (own connection).

    The role is a non-superuser with SELECT-only grants and
    `default_transaction_read_only`, so writes / file access / catalog secrets are
    refused by Postgres — the structural guarantee behind the app-layer guard. We
    also assert read-only + a statement timeout on the transaction as belt-and-
    suspenders in case the role was provisioned without those defaults."""
    from sqlalchemy import text

    with engine.connect() as conn, conn.begin():
        # SET TRANSACTION READ ONLY must be the first statement in the txn.
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        rows = conn.execute(text(sql)).mappings().fetchmany(50)
    return str([dict(row) for row in rows])


def _run_query_on_session(session, sql: str, timeout_ms: int) -> str:
    """Fallback path when no read-only role is configured: run on the agent's
    shared session inside a SAVEPOINT.

    The agent shares ONE session for both tool execution and its own state
    persistence, so a bad query (the model guessing a wrong column/table) would
    otherwise poison the whole run transaction. The savepoint rolls back only the
    failed statement, leaving the run recoverable. `SET LOCAL statement_timeout`
    bounds a slow/looping SELECT; the value is a sanitized int, safe to inline
    (SET takes no bound parameter). Results are capped so a large table can't
    bloat the output fed to the model."""
    from sqlalchemy import text

    with session.begin_nested():
        session.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        rows = session.execute(text(sql)).mappings().fetchmany(50)
    return str([dict(row) for row in rows])


def _fmt_tender(tender) -> str:
    title = tender.title or "(no title)"
    country = tender.buyer_country or "?"
    deadline = tender.deadline.date().isoformat() if tender.deadline else "n/a"
    # Lead with the public TED notice id (the human-facing identifier). `tender_id`
    # is the internal handle the model passes to find_matches — keep it OUT of any
    # user-facing label (ask_user options) per the UI convention.
    return (
        f"- TED {tender.ted_notice_id} | {title} | {country} | deadline={deadline} "
        f"(tender_id={tender.id})"
    )


def _find_tender(session, query: str) -> str:
    """Local tender lookup by internal id, TED notice id, or title text. No network."""
    import sqlalchemy as sa

    from app.db.models import Tender

    if not query:
        return "Provide a tender id, TED notice id, or words from its title."

    # A purely numeric query is treated as the internal id first.
    if query.isdigit():
        hit = session.get(Tender, int(query))
        if hit is not None:
            return "Found 1 tender:\n" + _fmt_tender(hit)

    # Match the public TED notice id (e.g. '420398-2026') or words in the title.
    like = f"%{query}%"
    rows = list(
        session.scalars(
            sa.select(Tender)
            .where(sa.or_(Tender.ted_notice_id.ilike(like), Tender.title.ilike(like)))
            .order_by(Tender.id.desc())
            .limit(_FIND_TENDER_LIMIT)
        ).all()
    )
    if not rows:
        return (
            f"No tenders in the local database match '{query}'. On a live run you "
            "may call ingest_tenders once to fetch recent notices and try again; "
            "otherwise ask the user to rephrase."
        )
    if len(rows) == 1:
        return "Found 1 tender:\n" + _fmt_tender(rows[0])
    body = "\n".join(_fmt_tender(t) for t in rows)
    return (
        f"Found {len(rows)} possible tenders for '{query}'. Use ask_user to let the "
        "user pick one — set each option's `id` to the tender_id and its `label` to "
        f"the TED notice id + title (do NOT put the internal tender_id in the label):"
        f"\n{body}"
    )


def _ingest_tenders(tool_args: dict, dry_run: bool, run_state: dict) -> str:
    days = max(1, min(int(tool_args.get("days_back", 1) or 1), _INGEST_TENDERS_MAX_DAYS))
    if dry_run:
        return (
            f"[dry-run] Would fetch construction/IT tenders from the last {days} "
            f"day(s) from live TED (limit {_INGEST_TENDERS_LIMIT}) and add new ones. "
            "No live call made in dry-run — re-run with dry_run=false to ingest."
        )
    if run_state.get("ingest_tenders_count", 0) >= 1:
        return "Already ingested tenders once this run — not repeating a live TED poll."
    run_state["ingest_tenders_count"] = run_state.get("ingest_tenders_count", 0) + 1
    try:
        from app.core.config import get_settings
        from app.ingestion.ted_client import poll_contract_notices

        settings = get_settings()
        summary = poll_contract_notices(
            cpv_codes=settings.cpv_code_list,
            days=days,
            dry_run=False,
            limit=_INGEST_TENDERS_LIMIT,
        )
        return f"Tender ingestion complete (live, bounded): {summary}. Now call find_tender again."
    except Exception as e:  # noqa: BLE001 — report, don't crash the loop
        return f"Error ingesting tenders: {e}"


def _ingest_awards(tool_args: dict, dry_run: bool, run_state: dict) -> str:
    months = max(
        1, min(int(tool_args.get("months_back", 1) or 1), _INGEST_AWARDS_MAX_MONTHS)
    )
    if dry_run:
        return (
            f"[dry-run] Would back-fill ~{months} month(s) of TED award notices to "
            "rebuild the supplier pool. No live call made in dry-run."
        )
    # Gate: ingest_awards is not a tender finder. Its only legitimate trigger is a
    # zero-result find_matches (no past winners fit the tender). Without this gate
    # the model would reach for it whenever it felt stuck — a heavy live back-fill.
    if not run_state.get("zero_match"):
        return (
            "ingest_awards refused: it is only permitted after find_matches returns "
            "zero matches (the supplier pool is already built from past awards). "
            "Run find_matches first."
        )
    if run_state.get("ingest_awards_count", 0) >= 1:
        return "Already back-filled awards once this run — not repeating."
    run_state["ingest_awards_count"] = run_state.get("ingest_awards_count", 0) + 1
    try:
        from app.core.config import get_settings
        from app.ingestion.awards_client import backfill_awards

        settings = get_settings()
        summary = backfill_awards(
            cpv_codes=settings.cpv_code_list, backfill_months=months, dry_run=False
        )
        return f"Awards back-fill complete (live, bounded): {summary}. Re-run find_matches."
    except Exception as e:  # noqa: BLE001
        return f"Error ingesting awards: {e}"


def dispatch_tool(
    tool_name: str,
    tool_args: dict,
    session,
    dry_run: bool = True,
    run_state: dict | None = None,
) -> str:
    """Dispatch a tool call to the backend logic. Returns a string for the model.

    `dry_run` makes the live-network tools (`ingest_tenders`, `ingest_awards`)
    no-op the network and report what they *would* do. `run_state` is the
    controller-owned per-run guard dict (caged-ingest counters + zero-match
    flag); it is optional so direct callers / `query_db` tests don't need it.
    """
    run_state = run_state if run_state is not None else {}

    if tool_name == "find_tender":
        return _find_tender(session, str(tool_args.get("query", "")).strip())

    if tool_name == "query_db":
        from app.core.config import get_settings
        from app.db.session import get_readonly_engine

        sql = str(tool_args.get("sql_query", ""))
        reason = _read_only_sql_error(sql)
        if reason is not None:
            return f"Error executing query: {reason}."
        clean_sql = sql.strip().rstrip(";")
        timeout_ms = int(get_settings().query_db_statement_timeout_ms)
        try:
            ro_engine = get_readonly_engine()
            if ro_engine is not None:
                # Structural P2 guarantee: run on a dedicated least-privilege
                # read-only role (own connection). Postgres itself refuses writes,
                # file access, and catalog secrets regardless of the app-layer
                # guard, and the separate connection can't poison the agent's
                # transaction, so no savepoint is needed here.
                return _run_query_readonly(ro_engine, clean_sql, timeout_ms)
            return _run_query_on_session(session, clean_sql, timeout_ms)
        except Exception as e:  # noqa: BLE001
            return f"Error executing query: {str(e)}"

    if tool_name == "find_matches":
        try:
            from app.matching.pipeline import MatchingPipeline

            tender_id = tool_args["tender_id"]
            top_n = tool_args.get("top_n")
            matches = MatchingPipeline().run(
                tender_id=tender_id, session=session, top_n=top_n or 3
            )
            # Record the zero-match flag so the ingest_awards gate can read it.
            run_state["zero_match"] = len(matches) == 0
            if not matches:
                return (
                    f"Matching complete for tender {tender_id}: 0 candidate suppliers "
                    "in the local pool (no past award winners fit this tender's "
                    "category/region)."
                )
            # Return the ranked rows + their sub-scores so the model can explain
            # each match from REAL pipeline output — it should not query_db with a
            # guessed schema to get this (the v5 scores are the grounding).
            lines = [
                f"- {m['company_name']} | final_score={m['final_score']} "
                f"[semantic={m['semantic_score']}, qualification={m['qualification_score']}, "
                f"location={m['location_score']}, budget={m['budget_score']}]"
                + (" (DISQUALIFIED)" if m["is_disqualified"] else "")
                for m in matches
            ]
            return (
                f"Matching complete for tender {tender_id}. Top {len(matches)} suppliers "
                "(ranked by the trained model — explain using ONLY these scores):\n"
                + "\n".join(lines)
            )
        except Exception as e:  # noqa: BLE001
            return f"Error finding matches: {str(e)}"

    if tool_name == "extract_tender_profile":
        try:
            from app.db.models import Tender
            from app.understanding.service import extract_and_store_tender_profile

            tender_id = tool_args["tender_id"]
            tender = session.get(Tender, tender_id)
            if tender is None:
                return f"No tender found for id {tender_id}."
            stored = extract_and_store_tender_profile(session, tender)
            meta = stored.get("_meta", {})
            certs = stored.get("required_certifications") or []
            return (
                f"Extracted profile for tender {tender_id} "
                f"(source={meta.get('source')}, validation_ok={meta.get('validation_ok')}). "
                f"Required certifications: {certs or 'none stated'}."
            )
        except Exception as e:  # noqa: BLE001
            return f"Error extracting tender profile: {str(e)}"

    if tool_name == "draft_email":
        try:
            from app.generation.drafter import EmailDrafter
            from app.generation.evidence import EvidenceExtractor

            match_id = tool_args["match_id"]
            evidence = EvidenceExtractor().collect(session, match_id)
            if evidence is None:
                return f"No match found for id {match_id}."
            draft = EmailDrafter().draft(evidence, recipient_type="supplier")
            return (
                f"Drafted supplier email ({draft['generator']}).\n"
                f"Subject: {draft['subject']}\n\n{draft['body']}"
            )
        except Exception as e:  # noqa: BLE001
            return f"Error drafting email: {str(e)}"

    if tool_name == "ingest_tenders":
        return _ingest_tenders(tool_args, dry_run, run_state)

    if tool_name == "ingest_awards":
        return _ingest_awards(tool_args, dry_run, run_state)

    if tool_name == "download_dossiers":
        # Removed from the agent surface (off-scope PDF scraping, G24). Guard in
        # case the model invents the old tool name.
        return (
            "download_dossiers is disabled for the agent (PDF portal scraping is "
            "out of scope). Use the locally stored tender data instead."
        )

    return f"Unknown tool '{tool_name}'."
