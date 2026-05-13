"""User feedback endpoints.

Captures thumbs up/down ratings on matches and email drafts. The feedback
loop feeds into the logistic-regression weight learner in Phase 5.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


# TODO: Phase 5 — accept thumbs-up/down + optional comment on a match
@router.post("/")
def submit_feedback() -> dict:
    ...
