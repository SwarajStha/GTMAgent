"""Semantic similarity scorer.

Computes cosine similarity between a tender embedding and a company
embedding, optionally averaging across the three ensemble models.
"""
from __future__ import annotations


class SemanticScorer:
    """Cosine similarity between two embedding vectors."""

    # TODO: Phase 3 — implement cosine similarity returning a [0, 1] score
    def score(self, tender_vec: list[float], company_vec: list[float]) -> float:
        ...
