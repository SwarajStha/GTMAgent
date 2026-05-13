"""Rule-based sub-scorers (budget, geography, qualification).

Each scorer returns a value in [0, 1] indicating how well the company
satisfies that single dimension. The weighted combination of these
sub-scores plus semantic similarity yields the final match score.
"""
from __future__ import annotations

from app.understanding.schemas import CompanyProfile, TenderProfile


class RuleScorer:
    """Bundle of rule-based sub-scorers."""

    # TODO: Phase 3 — score budget fit (company revenue vs tender budget)
    def score_budget(self, tender: TenderProfile, company: CompanyProfile) -> float:
        ...

    # TODO: Phase 3 — score geographic proximity / cross-border feasibility
    def score_location(self, tender: TenderProfile, company: CompanyProfile) -> float:
        ...

    # TODO: Phase 3 — score certification / capability overlap
    def score_qualification(self, tender: TenderProfile, company: CompanyProfile) -> float:
        ...
