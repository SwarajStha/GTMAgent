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


def _fmt_tender(tender) -> str:
    title = tender.title or "(no title)"
    country = tender.buyer_country or "?"
    deadline = tender.deadline.date().isoformat() if tender.deadline else "n/a"
    return f"- id={tender.id} | {title} | {country} | deadline={deadline}"


def _find_tender(session, query: str) -> str:
    """Local tender lookup by id or title text. Read-only, no network."""
    import sqlalchemy as sa

    from app.db.models import Tender

    if not query:
        return "Provide a tender id or words from its title to search for."

    # A purely numeric query is treated as an id first.
    if query.isdigit():
        hit = session.get(Tender, int(query))
        if hit is not None:
            return "Found 1 tender:\n" + _fmt_tender(hit)

    rows = list(
        session.scalars(
            sa.select(Tender)
            .where(Tender.title.ilike(f"%{query}%"))
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
        f"user pick one (pass each id as an option):\n{body}"
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
        from sqlalchemy import text

        sql = str(tool_args.get("sql_query", ""))
        reason = _read_only_sql_error(sql)
        if reason is not None:
            return f"Error executing query: {reason}."
        try:
            # Run inside a SAVEPOINT: the agent shares ONE session for both tool
            # execution and its own state persistence, so a bad query (e.g. the
            # model guessing a wrong column/table) would otherwise poison the whole
            # run transaction ("current transaction is aborted"). The savepoint
            # rolls back only the failed statement, leaving the run recoverable.
            # Cap results so a large table can't bloat the output fed to the model.
            with session.begin_nested():
                rows = session.execute(text(sql.strip().rstrip(";"))).mappings().fetchmany(50)
            return str([dict(row) for row in rows])
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
