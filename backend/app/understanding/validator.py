"""Post-extraction validation and repair.

Catches the typical LLM extraction failures (hallucinated CPVs, missing
budget when one is clearly present, etc.) and either repairs the value
or flags the record for human review.
"""
from __future__ import annotations

from app.understanding.schemas import TenderProfile


class ExtractionValidator:
    """Sanity-checks an extracted profile against the source text."""

    # TODO: Phase 2 — verify CPV format, deadline in future, budget plausible
    def validate_tender(self, profile: TenderProfile, raw_text: str) -> tuple[bool, list[str]]:
        ...
