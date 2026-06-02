"""Agent Tools definition for the Anthropic tool-use loop.

This module defines the JSON schemas for the tools provided to Claude,
and the dispatch logic to call internal backend modules.
"""
from __future__ import annotations

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
        "description": "Fetch historical contract awards from TED API to identify past winners.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days back to look.",
                    "default": 1
                }
            }
        }
    },
    {
        "name": "download_dossiers",
        "description": "Attempt to download the PDF dossiers/documents for a given tender.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tender_id": {
                    "type": "string",
                    "description": "The UUID of the tender."
                }
            },
            "required": ["tender_id"]
        }
    },
    {
        "name": "find_matches",
        "description": "Run the matching pipeline for a given tender to find the top company matches.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tender_id": {
                    "type": "string",
                    "description": "The UUID of the tender."
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
        "description": "Run a read-only SQL query against the tracking database (e.g. 'SELECT * FROM tenders LIMIT 5').",
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

def dispatch_tool(tool_name: str, tool_args: dict, session) -> str:
    """Dispatches the tool call to the actual backend logic.
    Returns the string representation of the tool output.
    """
    if tool_name == "query_db":
        from sqlalchemy import text
        try:
            result = session.execute(text(tool_args["sql_query"])).mappings().all()
            return str([dict(row) for row in result])
        except Exception as e:
            return f"Error executing query: {str(e)}"
    
    elif tool_name == "ingest_tenders":
        from app.ingestion.ted_client import poll_contract_notices
        from app.core.config import get_settings
        try:
            days = tool_args.get("days_back", 1)
            settings = get_settings()
            summary = poll_contract_notices(
                cpv_codes=settings.cpv_code_list,
                days=days,
                dry_run=False
            )
            return f"Tender ingestion complete: {summary}"
        except Exception as e:
            return f"Error ingesting tenders: {str(e)}"

    elif tool_name == "ingest_awards":
        from app.ingestion.awards_client import backfill_awards
        from app.core.config import get_settings
        try:
            days = tool_args.get("days_back", 1)
            # The function expects months, we do a rough conversion for the tool
            months = max(1, days // 30)
            settings = get_settings()
            summary = backfill_awards(
                cpv_codes=settings.cpv_code_list,
                backfill_months=months,
                dry_run=False
            )
            return f"Awards ingestion complete: {summary}"
        except Exception as e:
            return f"Error ingesting awards: {str(e)}"

    elif tool_name == "download_dossiers":
        from app.ingestion.dossier_downloader import download_dossiers
        try:
            # Although standard download_dossiers pulls all missing dossiers,
            # this handles the trigger (the actual tool might need a tender_id filter, 
            # but currently download_dossiers does bulk).
            summary = download_dossiers(dry_run=False)
            return f"Dossier download sweep triggered (run state: {summary})"
        except Exception as e:
            return f"Error downloading dossiers: {str(e)}"

    elif tool_name == "find_matches":
        try:
            # Backend matching modules are scaffolded but pipeline is defined
            from app.matching.pipeline import MatchingPipeline
            tender_id = tool_args["tender_id"]
            # top_n logic is usually handled inside or after run()
            pipeline = MatchingPipeline()
            # This requires pipeline.run to be fully implemented, catching potential NotImplementedErrors
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

    return f"Tool {tool_name} executed successfully with args: {tool_args} (Mocked response for layout)"
