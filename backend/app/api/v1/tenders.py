"""Tender list and detail endpoints.

When built, this router will expose:
  - GET  /api/v1/tenders            list with filtering/pagination
  - GET  /api/v1/tenders/{id}       single tender + extracted profile
  - POST /api/v1/tenders/ingest     manual trigger for an ingestion run
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


# TODO: Phase 2 — implement list endpoint with CPV / country / date filters
@router.get("/")
def list_tenders() -> dict:
    ...


# TODO: Phase 2 — implement tender detail endpoint
@router.get("/{tender_id}")
def get_tender(tender_id: str) -> dict:
    ...
