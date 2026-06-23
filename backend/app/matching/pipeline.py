"""Matching pipeline orchestrator (Layer 2).

`run(tender_id)` ranks the supplier pool (`company_profiles`, built by Layer 1)
for one tender and persists the result to the `matches` table.

Two scoring modes, chosen automatically:

* **v5 LR mode** (default when `exports/model_params.json` exists) — computes the
  10 v5 features per candidate (`features.compute_features`), narrows the pool
  with a v5-style hard filter (CPV-4 + country + value, progressive relaxation),
  and ranks by the trained Logistic Regression's win-probability
  (`lr_weights.LogisticRegressionScorer`). The 9 feature columns are persisted;
  the legacy 4 sub-scores are kept as rollups for API/frontend/email back-compat.
* **Legacy fixed-weight mode** (fallback when no params file) — the original
  semantic + budget + location + qualification weighted combine (0.40/0.20/0.20/
  0.20). Scores the whole pool. Preserves pre-Step-4 behavior so the app works
  before v5 is (re-)run.

Embedder / weights / scorer are injectable so unit tests run without
MiniLM/torch and without the params file.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import CompanyProfile, Document, Email, Match, Tender
from app.matching import features as feat
from app.matching.disqualifier import Disqualifier
from app.matching.embedder import EnsembleEmbedder
from app.matching.lr_weights import LogisticRegressionScorer
from app.matching.money import to_eur
from app.matching.rules import RuleScorer
from app.matching.semantic import SemanticScorer, cosine_similarity

# Default combiner weights for the legacy fallback path. Keys match the four
# legacy `matches` score columns.
DEFAULT_WEIGHTS: dict[str, float] = {
    "semantic": 0.40,
    "budget": 0.20,
    "location": 0.20,
    "qualification": 0.20,
}

_DOSSIER_TEXT_CHARS = 2000
_MAX_CANDIDATES = 200


class MatchingPipeline:
    """End-to-end matcher for one tender against the company-profile pool."""

    def __init__(
        self,
        embedder: EnsembleEmbedder | None = None,
        weights: dict[str, float] | None = None,
        lr_scorer: LogisticRegressionScorer | None = None,
        use_lr: bool = True,
    ) -> None:
        self.embedder = embedder or EnsembleEmbedder()
        self.semantic = SemanticScorer()
        self.rules = RuleScorer()
        self.disqualifier = Disqualifier()
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        # Load the active trained LR once (feedback-tuned model if present, else
        # the v5 base); None → legacy fixed-weight mode.
        self.lr_scorer = lr_scorer or (LogisticRegressionScorer.load_active() if use_lr else None)

    # ── tender helpers ───────────────────────────────────────────────────────

    def _tender_text(self, session: Session, tender: Tender) -> str:
        parts: list[str] = []
        if tender.title:
            parts.append(tender.title)
        # Procurement description (BT-24). v5 trained the tender/query side on
        # notice_title + description, and the company side already embeds award
        # descriptions (G6) — including it here aligns serve-time tender text with
        # training and enriches the semantic signal. NULL on pre-0012 rows → skipped.
        if tender.description:
            parts.append(tender.description)
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
    def _tender_cpvs(tender: Tender) -> list[str]:
        return [str(c) for c in (tender.cpv_codes or [])]

    @staticmethod
    def _tender_profile(tender: Tender) -> dict[str, Any]:
        """The structured Understanding-layer output stored on the tender (G11),
        or ``{}`` when the tender has not been run through extraction yet."""
        profile = getattr(tender, "tender_profile", None)
        return profile if isinstance(profile, dict) else {}

    @classmethod
    def _tender_required_certs(cls, tender: Tender) -> list[str]:
        """Required certifications extracted by the Understanding layer (G11/G12).
        Empty when no profile is stored — the cert gate then stays inert."""
        certs = cls._tender_profile(tender).get("required_certifications") or []
        return [str(c).strip() for c in certs if str(c).strip()]

    @classmethod
    def _tender_terms(cls, tender: Tender) -> list[str]:
        terms: list[str] = [str(c) for c in (tender.cpv_codes or [])]
        if tender.title:
            terms.append(tender.title)
        # Fold in the Understanding layer's required capabilities + keywords (G11)
        # so the legacy qualification scorer matches against real requirements,
        # not just the CPV code + title. (LR mode does not use rule terms; the
        # extracted certs feed its disqualifier gate instead.)
        profile = cls._tender_profile(tender)
        for key in ("required_capabilities", "keywords"):
            terms.extend(str(t).strip() for t in (profile.get(key) or []) if str(t).strip())
        return terms

    @staticmethod
    def _company_certs(company: CompanyProfile) -> tuple[list[str], bool]:
        """Return ``(certifications, known)`` for a company profile.

        The `company_profiles.certifications` JSONB is either a bare list or a
        ``{"items": [...], "known": bool}`` dict. `known` distinguishes "we
        checked and it holds none" from the MVP default "we have no cert data" —
        the disqualifier only gates on the former (see `Disqualifier.check`)."""
        raw = company.certifications
        if isinstance(raw, dict):
            items = [str(x).strip() for x in (raw.get("items") or []) if str(x).strip()]
            known = bool(raw.get("known")) if raw.get("known") is not None else bool(items)
            return items, known
        if isinstance(raw, list):
            items = [str(x).strip() for x in raw if str(x).strip()]
            return items, bool(items)
        return [], False

    # ── legacy fixed-weight combine ──────────────────────────────────────────

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
    def _explain_legacy(semantic: float, rule: dict[str, float]) -> str:
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

    @staticmethod
    def _explain_lr(contributions: dict[str, float]) -> str:
        top = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)[:3]
        return "Top factors: " + ", ".join(f"{name} {value:+.2f}" for name, value in top)

    # ── v5 hard filter (Python-side, progressive relaxation) ─────────────────

    @staticmethod
    def _hard_filter(
        candidates: list[CompanyProfile],
        tender_cpvs: list[str],
        tender_country: str | None,
        tender_budget: float | None,
        max_candidates: int = _MAX_CANDIDATES,
    ) -> list[CompanyProfile]:
        t4 = {feat._norm_cpv(c)[:4] for c in tender_cpvs if feat._norm_cpv(c)}
        t2 = {feat._norm_cpv(c)[:2] for c in tender_cpvs if feat._norm_cpv(c)}
        tc = (tender_country or "").strip().upper()

        def caps(c: CompanyProfile) -> dict[str, Any]:
            return c.capabilities or {}

        def cpv_prefixes(c: CompanyProfile, n: int) -> set[str]:
            codes = caps(c).get("cpv_codes") or []
            return {p[:n] for p in (feat._norm_cpv(x) for x in codes) if p}

        def in_country(c: CompanyProfile) -> bool:
            return bool(tc) and tc in [str(r).upper() for r in (caps(c).get("regions") or [])]

        def passes_value(c: CompanyProfile) -> bool:
            if tender_budget is None:
                return True
            med = (caps(c).get("deal_size_eur") or {}).get("median")
            if med and med > 0:
                return 0.01 <= (tender_budget / med) <= 100
            return True

        tiers = (
            lambda c: bool(t4 & cpv_prefixes(c, 4)) and in_country(c) and passes_value(c),
            lambda c: bool(t2 & cpv_prefixes(c, 2)) and in_country(c),
            lambda c: bool(t2 & cpv_prefixes(c, 2)),
            in_country,
        )
        for predicate in tiers:
            pool = [c for c in candidates if predicate(c)]
            if len(pool) >= 5:
                return pool[:max_candidates]
        return candidates[:max_candidates]

    # ── orchestration ──────────────────────────────────────────────────────

    def run(
        self,
        tender_id: int,
        session: Session | None = None,
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Score the pool for `tender_id`, persist `matches`, return ranked list."""
        own_session = session is None
        if own_session:
            from app.db.session import SessionLocal

            session = SessionLocal()
        try:
            tender = session.get(Tender, tender_id)
            if tender is None:
                raise ValueError(f"Tender {tender_id} not found")

            tender_vec = self.embedder.embed(self._tender_text(session, tender))
            tender_cpvs = self._tender_cpvs(tender)
            tender_terms = self._tender_terms(tender)
            # Certifications the Understanding layer extracted for this tender
            # (G11). Empty unless the tender was run through extraction → the cert
            # gate (G12) then stays inert (no structured requirement to enforce).
            required_certs = self._tender_required_certs(tender)
            # Convert the tender budget to EUR (G7). `budget_eur` is misnamed —
            # it's denominated in `tender.currency`; default missing currency to
            # EUR. Company deal sizes are already EUR (derive_deal_size), so this
            # makes the value features + capacity gate compare like-for-like.
            tender_eur = to_eur(tender.budget_eur, tender.currency or "EUR")

            candidates = list(
                session.scalars(
                    sa.select(CompanyProfile).where(CompanyProfile.embedding.is_not(None))
                ).all()
            )
            if self.lr_scorer is not None:
                candidates = self._hard_filter(
                    candidates, tender_cpvs, tender.buyer_country, tender_eur
                )

            # Idempotent recompute. Re-matching invalidates any emails grounded in
            # the previous (now-stale) matches, so drop those first to avoid the
            # emails_match_id_fkey violation (gap G26), then clear the matches.
            stale_match_ids = sa.select(Match.id).where(Match.tender_id == tender_id)
            session.execute(sa.delete(Email).where(Email.match_id.in_(stale_match_ids)))
            session.execute(sa.delete(Match).where(Match.tender_id == tender_id))

            results: list[dict[str, Any]] = []
            for company in candidates:
                caps = company.capabilities or {}
                deal = caps.get("deal_size_eur") or {}
                company_certs, certs_known = self._company_certs(company)
                disqualified, reasons = self.disqualifier.check(
                    tender_budget_eur=tender_eur,
                    required_certifications=required_certs,
                    company_certifications=company_certs,
                    company_certifications_known=certs_known,
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
                        weights=self._mode_metadata(),
                        is_disqualified=True,
                        explanation="Disqualified: " + "; ".join(reasons),
                    )
                elif self.lr_scorer is not None:
                    match = self._score_lr(
                        tender, tender_eur, tender_vec, tender_cpvs, company, caps
                    )
                else:
                    match = self._score_legacy(
                        tender, tender_eur, tender_vec, tender_terms, company, caps
                    )

                session.add(match)
                results.append(self._result_row(tender_id, company, match))

            session.commit()
            results.sort(key=lambda r: r["final_score"], reverse=True)
            return results[:top_n] if top_n else results
        finally:
            if own_session:
                session.close()

    # ── per-candidate scoring ────────────────────────────────────────────────

    def _score_lr(
        self,
        tender: Tender,
        tender_eur: float | None,
        tender_vec: list[float],
        tender_cpvs: list[str],
        company: CompanyProfile,
        caps: dict[str, Any],
    ) -> Match:
        # v5 semantic = clipped raw cosine (the LR was trained on this, not the
        # floor/span-mapped SemanticScorer value).
        semantic = max(0.0, min(1.0, cosine_similarity(tender_vec, list(company.embedding))))
        f = feat.compute_features(
            semantic_score=semantic,
            tender_cpvs=tender_cpvs,
            tender_nuts=None,  # contract-notice tenders carry no NUTS code yet
            tender_budget_eur=tender_eur,
            tender_country=tender.buyer_country,
            capabilities=caps,
        )
        final = round(float(self.lr_scorer.score(f)), 4)
        contributions = self.lr_scorer.contributions(f)
        return Match(
            tender_id=tender.id,
            company_id=company.id,
            # legacy rollups (kept for back-compat consumers)
            semantic_score=round(f["semantic_score"], 4),
            budget_score=round(f["value_score"], 4),
            location_score=round(f["country_match_score"], 4),
            qualification_score=round(max(f["cpv_4digit_score"], 0.5 * f["cpv_2digit_score"]), 4),
            # v5 feature columns
            cpv_4digit_score=f["cpv_4digit_score"],
            cpv_2digit_score=f["cpv_2digit_score"],
            nuts_exact_score=f["nuts_exact_score"],
            nuts_country_score=f["nuts_country_score"],
            value_score=f["value_score"],
            value_in_range_score=f["value_in_range_score"],
            country_match_score=f["country_match_score"],
            company_size_score=f["company_size_score"],
            competition_score=f["competition_score"],
            final_score=final,
            weights={**self.lr_scorer.as_metadata(), "features": f, "contributions": contributions},
            is_disqualified=False,
            explanation=self._explain_lr(contributions),
        )

    def _score_legacy(
        self,
        tender: Tender,
        tender_eur: float | None,
        tender_vec: list[float],
        tender_terms: list[str],
        company: CompanyProfile,
        caps: dict[str, Any],
    ) -> Match:
        semantic = self.semantic.score(tender_vec, list(company.embedding))
        rule = self.rules.score(
            tender_budget_eur=tender_eur,
            tender_country=tender.buyer_country,
            tender_terms=tender_terms,
            company_country=company.country,
            capabilities=caps,
        )
        final = self._combine(semantic, rule)
        return Match(
            tender_id=tender.id,
            company_id=company.id,
            semantic_score=semantic,
            budget_score=rule["budget_score"],
            location_score=rule["location_score"],
            qualification_score=rule["qualification_score"],
            final_score=final,
            weights=self.weights,
            is_disqualified=False,
            explanation=self._explain_legacy(semantic, rule),
        )

    def _mode_metadata(self) -> dict[str, Any]:
        return self.lr_scorer.as_metadata() if self.lr_scorer is not None else self.weights

    @staticmethod
    def _result_row(tender_id: int, company: CompanyProfile, match: Match) -> dict[str, Any]:
        return {
            "tender_id": tender_id,
            "company_id": str(company.id),
            "company_name": company.name,
            "semantic_score": match.semantic_score,
            "budget_score": match.budget_score,
            "location_score": match.location_score,
            "qualification_score": match.qualification_score,
            "final_score": match.final_score,
            "is_disqualified": match.is_disqualified,
        }
