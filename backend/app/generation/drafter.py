"""LLM email drafter (Claude, evidence-constrained).

Generates a subject + body for a B2B outreach email. The system prompt
forbids referencing any fact not present in the evidence payload.
"""
from __future__ import annotations


class EmailDrafter:
    """Wraps the Claude client and the drafting prompt templates."""

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model

    # TODO: Phase 4 — call Claude with evidence and return {subject, body}
    def draft(self, evidence: dict) -> dict:
        ...
