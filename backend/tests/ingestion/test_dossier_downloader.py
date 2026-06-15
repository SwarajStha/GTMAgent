"""Tests for ingestion.dossier_downloader + ingestion.__main__.

The 9 DB-touching tests use the `db_session` fixture from
backend/tests/conftest.py — a real Postgres transaction with full
rollback isolation. The pure-helper tests (1-5) need no fixtures.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from sqlalchemy import select, text

from app.db.models import Document, Tender
from app.ingestion import dossier_downloader as dd
from app.ingestion.dossier_downloader import (
    _is_pdf_content,
    compute_sha256,
    download_dossiers,
    extract_text_from_pdf,
)


_MINIMAL_PDF = b"%PDF-1.4\n%\xc4\xe5\xf2\xe5\xeb\xa7\xf3\xa0\xd0\n1 0 obj\n<<>>\nendobj\nxref\n0 1\n0000000000 65535 f\ntrailer\n<<>>\n%%EOF"


# ---------------------------------------------------------------------------
# 1-5: pure-helper tests (no DB, no network)
# ---------------------------------------------------------------------------


def test_is_pdf_content_by_content_type() -> None:
    assert _is_pdf_content("application/pdf", b"anything") is True
    assert _is_pdf_content("application/pdf; charset=binary", b"") is True


def test_is_pdf_content_by_magic_bytes() -> None:
    assert _is_pdf_content("text/html", b"%PDF-1.4 leaked into HTML wrapper") is True


def test_is_pdf_content_false_for_html() -> None:
    assert _is_pdf_content("text/html", b"<html><body>login</body></html>") is False
    assert _is_pdf_content(None, b"<!DOCTYPE html>") is False


def test_extract_text_returns_none_on_corrupt_bytes() -> None:
    # Must not raise; logs WARNING and returns None.
    assert extract_text_from_pdf(b"notapdf") is None


def test_extract_text_truncates_at_100k(monkeypatch: pytest.MonkeyPatch) -> None:
    big = "x" * 200_000

    class _FakePage:
        def get_text(self) -> str:
            return big

    class _FakeDoc:
        def __iter__(self):
            return iter([_FakePage()])

    monkeypatch.setattr(dd.fitz, "open", lambda **kw: _FakeDoc())
    result = extract_text_from_pdf(b"unused")
    assert result is not None
    assert len(result) == 100_000


# ---------------------------------------------------------------------------
# DB fixture helpers
# ---------------------------------------------------------------------------


def _insert_tender(db_session, ted_notice_id: str, document_url: str | None) -> Tender:
    """Insert a minimal Tender for use in download tests."""
    tender = Tender(
        ted_notice_id=ted_notice_id,
        cpv_codes=[],
        document_url=document_url,
        raw_json={"publication-number": ted_notice_id},
    )
    db_session.add(tender)
    db_session.flush()
    return tender


def _get_document(db_session, tender_id: int) -> Document | None:
    return db_session.execute(
        select(Document).where(Document.tender_id == tender_id)
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# 6-10: HTTP outcome tests (mocked via respx)
# ---------------------------------------------------------------------------


@respx.mock
def test_download_marks_tender_and_doc_restricted_on_401(
    db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simpler than mutating Settings: patch the lookup directly.
    monkeypatch.setattr(dd, "get_settings", lambda: _FakeSettings(tmp_path))

    url = "https://example.com/locked.pdf"
    tender = _insert_tender(db_session, "401-2026", url)
    respx.get(url).mock(return_value=httpx.Response(401))

    result = download_dossiers()

    assert result["restricted"] == 1
    assert result["downloaded"] == 0
    assert result["failed"] == 0

    db_session.expire_all()
    refreshed_tender = db_session.get(Tender, tender.id)
    assert refreshed_tender.is_restricted is True
    doc = _get_document(db_session, tender.id)
    assert doc is not None
    assert doc.is_restricted is True
    assert doc.storage_path is None


@respx.mock
def test_download_marks_restricted_on_403(
    db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dd, "get_settings", lambda: _FakeSettings(tmp_path))
    url = "https://example.com/forbidden.pdf"
    tender = _insert_tender(db_session, "403-2026", url)
    respx.get(url).mock(return_value=httpx.Response(403))

    result = download_dossiers()

    assert result["restricted"] == 1
    db_session.expire_all()
    assert db_session.get(Tender, tender.id).is_restricted is True
    assert _get_document(db_session, tender.id).is_restricted is True


@respx.mock
def test_download_marks_failed_on_timeout(
    db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dd, "get_settings", lambda: _FakeSettings(tmp_path))
    url = "https://example.com/slow.pdf"
    tender = _insert_tender(db_session, "timeout-2026", url)
    respx.get(url).mock(side_effect=httpx.TimeoutException("timed out"))

    result = download_dossiers()  # must not raise

    assert result["failed"] == 1
    assert result["downloaded"] == 0
    db_session.expire_all()
    doc = _get_document(db_session, tender.id)
    assert doc is not None
    assert doc.download_failed is True


@respx.mock
def test_download_marks_failed_on_html_200(
    db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dd, "get_settings", lambda: _FakeSettings(tmp_path))
    url = "https://example.com/login-wall.pdf"
    tender = _insert_tender(db_session, "html-2026", url)
    respx.get(url).mock(
        return_value=httpx.Response(
            200, content=b"<html><body>login</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    result = download_dossiers()

    assert result["failed"] == 1
    db_session.expire_all()
    assert _get_document(db_session, tender.id).download_failed is True


@respx.mock
def test_download_success_writes_file(
    db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dd, "get_settings", lambda: _FakeSettings(tmp_path))
    url = "https://example.com/dossier.pdf"
    tender = _insert_tender(db_session, "ok-2026", url)
    respx.get(url).mock(
        return_value=httpx.Response(
            200, content=_MINIMAL_PDF,
            headers={"content-type": "application/pdf"},
        )
    )

    result = download_dossiers()

    assert result["downloaded"] == 1
    assert result["failed"] == 0
    db_session.expire_all()
    doc = _get_document(db_session, tender.id)
    assert doc is not None
    assert doc.storage_path is not None
    assert doc.downloaded_at is not None
    assert doc.file_hash == compute_sha256(_MINIMAL_PDF)
    # File on disk.
    assert Path(doc.storage_path).exists()
    assert Path(doc.storage_path).read_bytes() == _MINIMAL_PDF


# ---------------------------------------------------------------------------
# 11-12: dedup tests (storage_path + file_hash)
# ---------------------------------------------------------------------------


@respx.mock
def test_idempotent_skip_by_storage_path(
    db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dd, "get_settings", lambda: _FakeSettings(tmp_path))
    url = "https://example.com/already.pdf"
    tender = _insert_tender(db_session, "done-2026", url)

    db_session.add(
        Document(
            tender_id=tender.id,
            source_url=url,
            storage_path=str(tmp_path / "already.pdf"),
            file_hash="deadbeef" * 8,
        )
    )
    db_session.flush()

    # respx route deliberately not registered — a real GET would explode,
    # proving the candidate was excluded from the query.
    result = download_dossiers()

    assert result["skipped_already_done"] == 1
    assert result["attempted"] == 0


@respx.mock
def test_idempotent_skip_by_file_hash(
    db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dd, "get_settings", lambda: _FakeSettings(tmp_path))
    sha = compute_sha256(_MINIMAL_PDF)

    # Pre-seed a different tender + Document with the same file_hash.
    other_tender = _insert_tender(db_session, "earlier-2026", "https://example.com/old.pdf")
    db_session.add(
        Document(
            tender_id=other_tender.id,
            source_url="https://example.com/old.pdf",
            storage_path=str(tmp_path / "earlier.pdf"),
            file_hash=sha,
        )
    )
    db_session.flush()

    url = "https://example.com/duplicate.pdf"
    tender = _insert_tender(db_session, "dup-2026", url)
    respx.get(url).mock(
        return_value=httpx.Response(
            200, content=_MINIMAL_PDF,
            headers={"content-type": "application/pdf"},
        )
    )

    result = download_dossiers()

    # `dup-2026` IS attempted (URL fetched) but the hash-check intercepts
    # before write. `earlier-2026` is excluded at the query level (it
    # already has storage_path). Both count toward skipped_already_done.
    assert result["attempted"] == 1
    assert result["downloaded"] == 0
    assert result["skipped_already_done"] == 2
    # No new file written under tender dir.
    assert not (tmp_path / "dup-2026").exists()


# ---------------------------------------------------------------------------
# 13-14: CLI tests
# ---------------------------------------------------------------------------


def test_cli_dry_run_no_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import __main__ as cli

    captured: dict[str, dict] = {}

    def _fake_poll(**kw):
        captured["contracts"] = kw
        return {"fetched": 0, "new": 0, "updated": 0, "errors": 0}

    def _fake_backfill(**kw):
        captured["awards"] = kw
        return {
            "fetched": 0, "new": 0, "updated": 0,
            "companies_created": 0, "skipped_no_winner": 0, "errors": 0,
        }

    def _fake_dossiers(**kw):
        captured["dossiers"] = kw
        return {
            "attempted": 0, "downloaded": 0, "restricted": 0,
            "failed": 0, "skipped_already_done": 0,
        }

    monkeypatch.setattr(cli, "poll_contract_notices", _fake_poll)
    monkeypatch.setattr(cli, "backfill_awards", _fake_backfill)
    monkeypatch.setattr(cli, "download_dossiers", _fake_dossiers)

    exit_code = cli.main(["--dry-run", "--cpv", "45000000"])

    assert exit_code == 0
    assert captured["contracts"]["dry_run"] is True
    assert captured["awards"]["dry_run"] is True
    assert captured["dossiers"]["dry_run"] is True


def test_cli_exit_1_on_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import __main__ as cli

    monkeypatch.setattr(
        cli,
        "poll_contract_notices",
        lambda **kw: {"fetched": 0, "new": 0, "updated": 0, "errors": 0},
    )
    monkeypatch.setattr(
        cli,
        "backfill_awards",
        lambda **kw: {
            "fetched": 0, "new": 0, "updated": 0,
            "companies_created": 0, "skipped_no_winner": 0, "errors": 0,
        },
    )
    monkeypatch.setattr(
        cli,
        "download_dossiers",
        lambda **kw: {
            "attempted": 2, "downloaded": 0, "restricted": 0,
            "failed": 2, "skipped_already_done": 0,
        },
    )

    exit_code = cli.main(["--cpv", "45000000"])
    assert exit_code == 1


# ---------------------------------------------------------------------------
# helper: a stand-in Settings for download_dossiers (avoids touching real .env)
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Just the two fields download_dossiers actually reads."""

    def __init__(self, storage_path: Path) -> None:
        self.dossier_storage_path = str(storage_path)
        self.dossier_timeout = 5
