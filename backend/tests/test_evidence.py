"""DB-backed tests for the centralized EvidenceExtractor (G10)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db.models import CompanyProfile, Document, Match, Tender
from app.generation.evidence import EvidenceExtractor


def test_collect_builds_evidence_dict(db_session) -> None:
    tender = Tender(
        ted_notice_id="EV-1",
        title="Clinic construction works",
        buyer_name="Stadt Wittmund",
        buyer_country="DE",
        cpv_codes=["45000000"],
        raw_json={"source": "test"},
    )
    company = CompanyProfile(name="Bau GmbH", country="DE", capabilities={})
    db_session.add_all([tender, company])
    db_session.flush()

    match = Match(
        tender_id=tender.id,
        company_id=company.id,
        semantic_score=0.4,
        budget_score=0.5,
        location_score=1.0,
        qualification_score=1.0,
        final_score=0.3,
        explanation="Strong CPV overlap.",
    )
    document = Document(
        tender_id=tender.id,
        source_url="https://ted.europa.eu/dossier/source.pdf",
        storage_path="/storage/dossiers/EV-1/notice.pdf",
        extracted_text="Clinic construction works and BIM coordination.",
        downloaded_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    db_session.add_all([match, document])
    db_session.flush()

    evidence = EvidenceExtractor().collect(db_session, match.id)

    assert evidence is not None
    assert evidence["company"]["name"] == "Bau GmbH"
    assert evidence["tender"]["ted_notice_id"] == "EV-1"
    assert evidence["score_breakdown"]["final_score"] == 0.3
    assert evidence["match_explanation"] == "Strong CPV overlap."
    assert evidence["document_snippets"][0]["filename"] == "notice.pdf"
    assert "Clinic construction" in evidence["document_snippets"][0]["snippet"]


def test_collect_accepts_string_match_id(db_session) -> None:
    tender = Tender(ted_notice_id="EV-2", raw_json={}, cpv_codes=[])
    company = CompanyProfile(name="Co", capabilities={})
    db_session.add_all([tender, company])
    db_session.flush()
    match = Match(tender_id=tender.id, company_id=company.id, final_score=0.1)
    db_session.add(match)
    db_session.flush()

    evidence = EvidenceExtractor().collect(db_session, str(match.id))
    assert evidence is not None
    assert evidence["document_snippets"] == []  # no dossiers


def test_collect_returns_none_for_missing_match(db_session) -> None:
    assert EvidenceExtractor().collect(db_session, uuid.uuid4()) is None
