"""LLM-driven field extraction using Claude Sonnet 4.6.

Given raw tender or company text, produces a validated `TenderProfile`
or `CompanyProfile` instance. Uses Claude's tool-use API to enforce the
JSON shape declaratively.
"""
from __future__ import annotations

from app.understanding.schemas import CompanyProfile, TenderProfile


class FieldExtractor:
    """Wraps the Claude client and the extraction prompt templates."""

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model

    # TODO: Phase 2 — call Claude with the tender extraction tool schema
    def extract_tender(self, raw_text: str) -> TenderProfile:
        ...

    # TODO: Phase 2 — call Claude with the company extraction tool schema
    def extract_company(self, raw_text: str) -> CompanyProfile:
        ...
