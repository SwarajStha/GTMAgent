"""Outreach email generation endpoints.

When built, this router will expose:
  - POST /api/v1/emails/{match_id}/generate    draft an outreach email
  - GET  /api/v1/emails/{email_id}             fetch a stored draft
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


# TODO: Phase 4 — generate evidence-grounded email draft via Claude
@router.post("/{match_id}/generate")
def generate_email(match_id: str) -> dict:
    ...


# TODO: Phase 4 — fetch a stored email draft by id
@router.get("/{email_id}")
def get_email(email_id: str) -> dict:
    ...
