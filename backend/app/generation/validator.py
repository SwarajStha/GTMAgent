"""Output guardrails for generated emails.

A lightweight structural check the drafter runs on an LLM draft before accepting
it: a draft must have a non-empty subject and body within sane length budgets,
otherwise the drafter falls back to the deterministic template. (Full
evidence-claim verification — rejecting facts absent from the evidence set — is
left to the evidence-constrained system prompt for now; this guards shape.)
"""
from __future__ import annotations

from typing import Any


class EmailValidator:
    """Validates a drafted email against basic guardrail rules."""

    MAX_SUBJECT_CHARS = 200
    MAX_BODY_CHARS = 4000
    MIN_BODY_CHARS = 20

    def validate(self, draft: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, list[str]]:
        """Return ``(is_valid, reasons)`` for a ``{"subject", "body"}`` draft."""
        reasons: list[str] = []
        subject = str(draft.get("subject") or "").strip()
        body = str(draft.get("body") or "").strip()

        if not subject:
            reasons.append("missing subject")
        elif len(subject) > self.MAX_SUBJECT_CHARS:
            reasons.append("subject too long")

        if not body:
            reasons.append("missing body")
        elif len(body) < self.MIN_BODY_CHARS:
            reasons.append("body too short")
        elif len(body) > self.MAX_BODY_CHARS:
            reasons.append("body too long")

        return (not reasons, reasons)
