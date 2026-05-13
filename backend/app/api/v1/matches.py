"""Match result endpoints.

When built, this router will expose ranked company-tender matches together
with the per-rule sub-scores and the LLM-generated explanation string.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


# TODO: Phase 3 — return paged matches for a given tender or company
@router.get("/")
def list_matches() -> dict:
    ...


# TODO: Phase 3 — return a single match including evidence + explanation
@router.get("/{match_id}")
def get_match(match_id: str) -> dict:
    ...
