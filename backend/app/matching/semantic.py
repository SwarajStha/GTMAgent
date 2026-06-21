"""Semantic similarity scorer.

Cosine similarity between a tender embedding and a company-profile embedding,
mapped into a [0, 1] match score. Kept dependency-free (pure Python) so it is
unit-testable without numpy / torch; the embedding *vectors* are produced
separately by `embedder.py`.
"""
from __future__ import annotations

from collections.abc import Sequence
from math import sqrt

# Raw cosine is remapped to [0, 1] with the ML-spike curve: values at/under
# ~0.05 floor to 0, values at/over ~0.95 saturate at 1. Sentence-embedding
# cosines for unrelated text cluster low, so this spreads the useful range.
_COSINE_FLOOR = 0.05
_COSINE_SPAN = 0.90


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Raw cosine similarity in [-1, 1]; 0.0 for empty/zero/mismatched vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticScorer:
    """Cosine similarity between two embedding vectors, mapped to [0, 1]."""

    def score(self, tender_vec: Sequence[float], company_vec: Sequence[float]) -> float:
        cosine = cosine_similarity(tender_vec, company_vec)
        mapped = (cosine - _COSINE_FLOOR) / _COSINE_SPAN
        return round(max(0.0, min(1.0, mapped)), 4)
