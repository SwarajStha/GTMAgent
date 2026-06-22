"""End-to-end tests for MatchingPipeline.run against the real gtm_test schema.

A keyword-discriminating fake embedder stands in for MiniLM so the test is
deterministic and torch-free while still exercising real semantic ranking.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.db.models import CompanyProfile, Email, Match, Tender
from app.matching.features import FEATURE_NAMES
from app.matching.lr_weights import LogisticRegressionScorer
from app.matching.pipeline import MatchingPipeline


class _KeywordEmbedder:
    """Maps text to a sparse 384-d vector via a few keyword channels, so related
    texts share a channel (cosine ~1) and unrelated ones are orthogonal (~0)."""

    CHANNELS = ["floor", "parquet", "software", "cloud", "road"]

    def embed(self, text: str, model: str = "all-MiniLM-L6-v2") -> list[float]:
        t = (text or "").lower()
        vec = [0.0] * 384
        hit = False
        for i, kw in enumerate(self.CHANNELS):
            if kw in t:
                vec[i] = 1.0
                hit = True
        if not hit:
            vec[383] = 1.0
        return vec


def _tender(**kw: object) -> Tender:
    base = {
        "ted_notice_id": "T-PIPE-1",
        "title": "Parquet flooring works for public building",
        "buyer_country": "DE",
        "cpv_codes": ["45000000"],
        "budget_eur": 100_000.0,
        "deadline": datetime(2026, 9, 1, tzinfo=UTC),
        "raw_json": {"publication-number": "T-PIPE-1"},
    }
    base.update(kw)
    return Tender(**base)


def _profile(name: str, text: str, embedder: _KeywordEmbedder, **caps: object) -> CompanyProfile:
    capabilities = {
        "text": text,
        "cpv_codes": caps.get("cpv_codes", []),
        "deal_size_eur": caps.get("deal_size_eur", {"min": 30_000, "max": 500_000}),
        "regions": caps.get("regions", []),
    }
    return CompanyProfile(
        name=name,
        country=caps.get("country"),
        capabilities=capabilities,
        embedding=embedder.embed(text),
    )


def test_tender_text_includes_description(db_session) -> None:
    # The matcher must fold tender.description into the embedding text (aligns
    # serve-time text with v5 training; companies already embed descriptions).
    tender = _tender(
        title="Road resurfacing works",
        description="Resurface 12km of motorway carriageway near Brno.",
    )
    db_session.add(tender)
    db_session.flush()
    pipe = MatchingPipeline(embedder=_KeywordEmbedder(), use_lr=False)
    text = pipe._tender_text(db_session, tender)
    assert "Road resurfacing works" in text
    assert "Resurface 12km of motorway carriageway near Brno." in text


def test_pipeline_ranks_relevant_company_first(db_session) -> None:
    embedder = _KeywordEmbedder()
    tender = _tender()
    db_session.add(tender)
    db_session.flush()

    flooring = _profile(
        "Floor Pros GmbH", "parquet floor specialist", embedder,
        cpv_codes=["45000000"], regions=["DE"], country="DE",
    )
    it_co = _profile(
        "Cloud Soft SARL", "cloud software services", embedder,
        cpv_codes=["72000000"], regions=["FR"], country="FR",
    )
    db_session.add_all([flooring, it_co])
    db_session.flush()

    results = MatchingPipeline(embedder=embedder).run(tender.id, session=db_session)

    assert [r["company_name"] for r in results][0] == "Floor Pros GmbH"
    assert results[0]["final_score"] > results[1]["final_score"]
    assert results[0]["semantic_score"] == 1.0  # same keyword channel
    assert results[1]["semantic_score"] == 0.0  # orthogonal

    # Persisted to matches, ranked, not disqualified.
    rows = db_session.query(Match).filter_by(tender_id=tender.id).all()
    assert len(rows) == 2
    assert all(r.is_disqualified is False for r in rows)
    assert all(r.weights for r in rows)


def test_pipeline_is_idempotent(db_session) -> None:
    embedder = _KeywordEmbedder()
    tender = _tender()
    db_session.add(tender)
    db_session.flush()
    db_session.add(_profile("Floor Pros", "parquet floor", embedder, cpv_codes=["45000000"]))
    db_session.flush()

    pipe = MatchingPipeline(embedder=embedder)
    pipe.run(tender.id, session=db_session)
    pipe.run(tender.id, session=db_session)

    assert db_session.query(Match).filter_by(tender_id=tender.id).count() == 1


def test_pipeline_disqualifies_over_capacity_company(db_session) -> None:
    embedder = _KeywordEmbedder()
    tender = _tender(budget_eur=5_000_000.0)  # far over the small company's capacity
    db_session.add(tender)
    db_session.flush()
    db_session.add(
        _profile(
            "Tiny Co", "parquet floor", embedder,
            cpv_codes=["45000000"], deal_size_eur={"min": 1_000, "max": 10_000},
        )
    )
    db_session.flush()

    results = MatchingPipeline(embedder=embedder).run(tender.id, session=db_session)

    assert results[0]["is_disqualified"] is True
    assert results[0]["final_score"] == 0.0
    row = db_session.query(Match).filter_by(tender_id=tender.id).one()
    assert row.is_disqualified is True
    assert "Disqualified" in row.explanation


def test_pipeline_top_n_limits_results(db_session) -> None:
    embedder = _KeywordEmbedder()
    tender = _tender()
    db_session.add(tender)
    db_session.flush()
    db_session.add_all([
        _profile("A", "parquet floor", embedder, cpv_codes=["45000000"]),
        _profile("B", "road construction", embedder, cpv_codes=["45000000"]),
        _profile("C", "cloud software", embedder, cpv_codes=["72000000"]),
    ])
    db_session.flush()

    results = MatchingPipeline(embedder=embedder).run(tender.id, session=db_session, top_n=2)
    assert len(results) == 2
    # but all three are persisted
    assert db_session.query(Match).filter_by(tender_id=tender.id).count() == 3


def _cpv4_scorer() -> LogisticRegressionScorer:
    """A trained-LR stand-in that weights only cpv_4digit_score (identity scaler)."""
    coef = [0.0] * len(FEATURE_NAMES)
    coef[FEATURE_NAMES.index("cpv_4digit_score")] = 5.0
    return LogisticRegressionScorer(
        feature_names=FEATURE_NAMES,
        coefficients=coef,
        intercept=0.0,
        scaler_mean=[0.0] * len(FEATURE_NAMES),
        scaler_scale=[1.0] * len(FEATURE_NAMES),
    )


def test_pipeline_lr_mode_populates_feature_columns(db_session) -> None:
    embedder = _KeywordEmbedder()
    tender = _tender(cpv_codes=["45000000"])
    db_session.add(tender)
    db_session.flush()
    db_session.add_all([
        _profile("Bau GmbH", "parquet floor", embedder,
                 cpv_codes=["45000000"], regions=["DE"], country="DE"),
        _profile("Soft SARL", "cloud software", embedder,
                 cpv_codes=["72000000"], regions=["FR"], country="FR"),
    ])
    db_session.flush()

    results = MatchingPipeline(embedder=embedder, lr_scorer=_cpv4_scorer()).run(
        tender.id, session=db_session
    )
    # cpv_4digit dominates → the construction company ranks first.
    assert results[0]["company_name"] == "Bau GmbH"
    assert results[0]["final_score"] > results[1]["final_score"]

    matches = db_session.query(Match).filter_by(tender_id=tender.id).all()
    constr = next(m for m in matches if m.cpv_4digit_score == 1.0)
    assert constr.competition_score == 0.5          # v5 feature columns populated
    assert constr.value_score is not None
    assert constr.location_score == 1.0             # rollup: country_match (DE in [DE])
    assert constr.weights and "features" in constr.weights and "contributions" in constr.weights
    assert any(m.cpv_4digit_score == 0.0 for m in matches)  # the IT company


def test_pipeline_rematch_deletes_dependent_emails(db_session) -> None:
    # Regression for G26: re-matching a tender whose match was turned into an
    # email must not hit emails_match_id_fkey on the idempotent DELETE.
    embedder = _KeywordEmbedder()
    tender = _tender()
    db_session.add(tender)
    db_session.flush()
    db_session.add(_profile("Floor Pros", "parquet floor", embedder, cpv_codes=["45000000"]))
    db_session.flush()

    pipe = MatchingPipeline(embedder=embedder)
    pipe.run(tender.id, session=db_session)
    match = db_session.query(Match).filter_by(tender_id=tender.id).first()
    db_session.add(Email(
        match_id=match.id, tender_id=tender.id, recipient_type="buyer",
        subject="s", body="b", status="draft",
    ))
    db_session.flush()

    pipe.run(tender.id, session=db_session)  # must not raise

    assert db_session.query(Match).filter_by(tender_id=tender.id).count() == 1
    assert db_session.query(Email).filter_by(tender_id=tender.id).count() == 0
