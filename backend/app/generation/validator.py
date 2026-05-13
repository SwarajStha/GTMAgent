"""Output guardrails for generated emails.

Rejects drafts that mention claims absent from the evidence set, contain
prohibited phrases, exceed a length budget, or fail basic deliverability
heuristics (e.g., no subject line).
"""
from __future__ import annotations


class EmailValidator:
    """Validates a drafted email against guardrail rules."""

    # TODO: Phase 4 — return (is_valid, reasons[]) for a draft
    def validate(self, draft: dict, evidence: dict) -> tuple[bool, list[str]]:
        ...
