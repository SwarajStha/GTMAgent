"""Matching pipeline orchestrator.

Flow per (tender, candidate-pool):
  1. Disqualifier filters the pool
  2. EnsembleEmbedder + SemanticScorer score remaining pairs
  3. RuleScorer adds budget / geo / qualification sub-scores
  4. Weighted combiner (LR-learned weights) produces the final score
  5. Rows are persisted to the `matches` table with explanation strings
"""
from __future__ import annotations

from app.matching.disqualifier import Disqualifier
from app.matching.embedder import EnsembleEmbedder
from app.matching.rules import RuleScorer
from app.matching.semantic import SemanticScorer


class MatchingPipeline:
    """End-to-end matcher for one tender against many candidate companies."""

    def __init__(self) -> None:
        self.disqualifier = Disqualifier()
        self.embedder = EnsembleEmbedder()
        self.semantic = SemanticScorer()
        self.rules = RuleScorer()

    # TODO: Phase 3 — run the full pipeline and persist results
    def run(self, tender_id: str) -> list[dict]:
        ...
