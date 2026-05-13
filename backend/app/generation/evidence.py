"""Evidence extractor.

Pulls the concrete factual snippets the drafter will cite from the
tender profile, dossier text, and company profile. The drafter is
constrained to only mention facts present in this evidence set.
"""
from __future__ import annotations


class EvidenceExtractor:
    """Collects citations for a single (tender, company) match."""

    # TODO: Phase 4 — return a structured evidence dict for the drafter prompt
    def collect(self, match_id: str) -> dict:
        ...
