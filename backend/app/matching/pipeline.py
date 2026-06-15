"""Matching pipeline orchestrator (Layer 2).

`run(tender_id)` ranks the supplier pool (`company_profiles`, built by Layer 1)
for one tender and persists the result to the `matches` table:

  1. derive the tender's text + terms (MVP: from its own columns + dossier text)
  2. embed the tender once; load candidate company_profiles
  3. per candidate: hard-disqualify, else score semantic + budget + location +
     qualification, combine with weights -> final_score
  4. replace this tender's `matches` rows (idempotent recompute) and return the
     ranked list

Embedder/weights are injectable so unit tests run without MiniLM/torch.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import CompanyProfile, Document, Match, Tender
from app.matching.disqualifier import Disqualifier
from app.matching.embedder import EnsembleEmbedder
from app.matching.rules import RuleScorer
from app.matching.semantic import SemanticScorer

# Default combiner weights for the four sub-scores (Phase 5 LR learning will
# replace these from feedback). Keys match the `matches` score columns.
DEFAULT_WEIGHTS: dict[str, float] = {
    "semantic": 0.40,
    "budget": 0.20,
    "location": 0.20,
    "qualification": 0.20,
}

_DOSSIER_TEXT_CHARS = 2000


class MatchingPipeline:
    """End-to-end matcher for one tender against the company-profile pool."""

    def __init__(
        self,
        embedder: EnsembleEmbedder | None = None,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.embedder = embedder or EnsembleEmbedder()
        self.semantic = SemanticScorer()
        self.rules = RuleScorer()
        self.disqualifier = Disqualifier()
        self.weights = weights or dict(DEFAULT_WEIGHTS)

    # ── helpers ────────────────────────────────────────────────────────────

    def _tender_text(self, session: Session, tender: Tender) -> str:
        parts: list[str] = []
        if tender.title:
            parts.append(tender.title)
        if tender.cpv_codes:
            parts.append("CPV: " + ", ".join(str(c) for c in tender.cpv_codes))
        doc_text = session.scalar(
            sa.select(Document.extracted_text)
            .where(Document.tender_id == tender.id)
            .where(Document.extracted_text.is_not(None))
            .limit(1)
        )
        if doc_text:
            parts.append(doc_text[:_DOSSIER_TEXT_CHARS])
        return ". ".join(parts) if parts else (tender.ted_notice_id or "")

    @staticmethod
    def _tender_terms(tender: Tender) -> list[str]:
        terms: list[str] = [str(c) for c in (tender.cpv_codes or [])]
        if tender.title:
            terms.append(tender.title)
        return terms

    def _combine(self, semantic: float, rule: dict[str, float]) -> float:
        w = self.weights
        scores = {
            "semantic": semantic,
            "budget": rule["budget_score"],
            "location": rule["location_score"],
            "qualification": rule["qualification_score"],
        }
        total = sum(max(0.0, w.get(k, 0.0)) for k in scores)
        if total == 0:
            return 0.0
        combined = sum(max(0.0, w.get(k, 0.0)) * v for k, v in scores.items()) / total
        return round(combined, 4)

    @staticmethod
    def _explain(semantic: float, rule: dict[str, float]) -> str:
        ordered = sorted(
            {
                "semantic": semantic,
                "qualification": rule["qualification_score"],
                "location": rule["location_score"],
                "budget": rule["budget_score"],
            }.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )
        return "Match factors: " + ", ".join(f"{name} {value:.2f}" for name, value in ordered)

    # ── orchestration ──────────────────────────────────────────────────────

    def run(
        self,
        tender_id: int,
        session: Session | None = None,
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Score the pool for `tender_id`, persist `matches`, return ranked list.

        `session` is injectable for tests; when omitted a `SessionLocal()` is
        opened and closed here (so the agent's `find_matches` tool can call it
        with just a tender id).
        """
        own_session = session is None
        if own_session:
            from app.db.session import SessionLocal

            session = SessionLocal()
        try:
            tender = session.get(Tender, tender_id)
            if tender is None:
                raise ValueError(f"Tender {tender_id} not found")

            tender_vec = self.embedder.embed(self._tender_text(session, tender))
            tender_terms = self._tender_terms(tender)

            candidates = session.scalars(
                sa.select(CompanyProfile).where(CompanyProfile.embedding.is_not(None))
            ).all()

            # Idempotent recompute: clear this tender's previous matches first.
            session.execute(sa.delete(Match).where(Match.tender_id == tender_id))

            results: list[dict[str, Any]] = []
            for company in candidates:
                caps = company.capabilities or {}
                deal = caps.get("deal_size_eur") or {}
                disqualified, reasons = self.disqualifier.check(
                    tender_budget_eur=tender.budget_eur,
                    required_certifications=[],  # MVP: tenders lack structured cert reqs
                    company_certifications=[],
                    deal_max=deal.get("max"),
                )

                if disqualified:
                    match = Match(
                        tender_id=tender_id,
                        company_id=company.id,
                        semantic_score=0.0,
                        budget_score=0.0,
                        location_score=0.0,
                        qualification_score=0.0,
                        final_score=0.0,
                        weights=self.weights,
                        is_disqualified=True,
                        explanation="Disqualified: " + "; ".join(reasons),
                    )
                else:
                    semantic = self.semantic.score(tender_vec, list(company.embedding))
                    rule = self.rules.score(
                        tender_budget_eur=tender.budget_eur,
                        tender_country=tender.buyer_country,
                        tender_terms=tender_terms,
                        company_country=company.country,
                        capabilities=caps,
                    )
                    final = self._combine(semantic, rule)
                    match = Match(
                        tender_id=tender_id,
                        company_id=company.id,
                        semantic_score=semantic,
                        budget_score=rule["budget_score"],
                        location_score=rule["location_score"],
                        qualification_score=rule["qualification_score"],
                        final_score=final,
                        weights=self.weights,
                        is_disqualified=False,
                        explanation=self._explain(semantic, rule),
                    )

                session.add(match)
                results.append({
                    "tender_id": tender_id,
                    "company_id": str(company.id),
                    "company_name": company.name,
                    "semantic_score": match.semantic_score,
                    "budget_score": match.budget_score,
                    "location_score": match.location_score,
                    "qualification_score": match.qualification_score,
                    "final_score": match.final_score,
                    "is_disqualified": match.is_disqualified,
                })

            session.commit()
            results.sort(key=lambda r: r["final_score"], reverse=True)
            return results[:top_n] if top_n else results
        finally:
            if own_session:
                session.close()
