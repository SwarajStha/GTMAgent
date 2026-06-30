"""Human-readable progress lines for the agent's SSE stream.

Deterministic + tool-derived — no extra LLM call. The controller emits one of
these *before* each blocking step so the UI shows what is happening
("Looking up the tender…", "Fetching recent tenders from TED…") instead of a
frozen spinner. Keeping the mapping here (not in the model's hands) means the
status text can't be hallucinated and stays stable across runs.
"""
from __future__ import annotations

from typing import Any

# Friendly status line per tool. Mirrors the tool surface in app.agent.tools.
_TOOL_PROGRESS: dict[str, str] = {
    "find_tender": "Looking up the tender in our local database…",
    "find_matches": "Ranking the supplier pool for this tender…",
    "query_db": "Reading the database…",
    "extract_tender_profile": "Reading the tender's requirements…",
    "draft_email": "Drafting the outreach email…",
    "ingest_tenders": "No local match — fetching recent tenders from TED…",
    "ingest_awards": "Rebuilding the supplier pool from past awards…",
    "ask_user": "Need a quick clarification…",
}

# Emitted before each Claude turn and just before the final summary.
THINKING = "Thinking…"
FINALIZING = "Writing the summary…"


def progress_message(tool_name: str, args: dict[str, Any] | None = None) -> str:
    """Friendly status line for an about-to-run tool."""
    return _TOOL_PROGRESS.get(tool_name, f"Running {tool_name}…")
