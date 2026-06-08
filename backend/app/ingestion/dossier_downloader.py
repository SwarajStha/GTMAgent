"""TED tender dossier downloader (Job 3).

Walks the `tenders` table for rows with a non-null `document_url` that
have not yet been successfully fetched, downloads each PDF via httpx,
extracts text via PyMuPDF, and upserts one `documents` row per tender.

No authentication is attempted — buyer portals returning 401/403 are
flagged `Tender.is_restricted = True` so we don't re-attempt them on
the next sweep.

The dedup story has two layers:
  * `Document.storage_path` populated → skip (already downloaded).
  * Same `Document.file_hash` already exists on another tender → skip
    (the same PDF is re-published under multiple tenders; one copy is
    enough).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document, Tender
from app.db.session import get_session

logger = logging.getLogger(__name__)

_TEXT_CAP = 100_000
_USER_AGENT = "GTMAgent/0.1 (TUM CITHN2014 course project)"


# ---------------------------------------------------------------------------
# pure helpers (unit-testable without DB or network)
# ---------------------------------------------------------------------------


def compute_sha256(data: bytes) -> str:
    """Hex-encoded SHA-256 of `data`. Used as the dedup key on `documents.file_hash`."""
    return hashlib.sha256(data).hexdigest()


def _is_pdf_content(content_type: str | None, body: bytes) -> bool:
    """True if the response is a PDF.

    Trusts EITHER the `Content-Type` header (`*pdf*`) OR the file magic
    (`%PDF` prefix). Catches portals that serve an HTML login page with
    HTTP 200 + `text/html`.
    """
    if content_type and "pdf" in content_type.lower():
        return True
    return body[:4] == b"%PDF"


def extract_text_from_pdf(pdf_bytes: bytes) -> str | None:
    """Extract concatenated text from `pdf_bytes` using PyMuPDF.

    Capped at `_TEXT_CAP` characters (truncated silently if longer).
    Returns None and logs WARNING on any extraction failure — never
    raises, so the caller can keep iterating other dossiers.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        if len(text) > _TEXT_CAP:
            text = text[:_TEXT_CAP]
        return text
    except Exception as exc:
        logger.warning("PDF extraction failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _upsert_document(session: Session, **values: Any) -> None:
    """ON CONFLICT (tender_id) DO UPDATE on `documents`.

    Caller passes `tender_id` plus any subset of columns to set on
    INSERT and to overwrite on UPDATE.
    """
    stmt = pg_insert(Document).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k != "tender_id"}
    if update_cols:
        stmt = stmt.on_conflict_do_update(
            index_elements=["tender_id"], set_=update_cols
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=["tender_id"])
    session.execute(stmt)


def _file_hash_exists(session: Session, sha256: str) -> bool:
    return (
        session.execute(
            select(Document.id).where(Document.file_hash == sha256).limit(1)
        ).scalar_one_or_none()
        is not None
    )


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def download_dossiers(
    dry_run: bool = False,
    verbose: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Download dossier PDFs for tenders that need one.

    Returns ``{"attempted": N, "downloaded": N, "restricted": N,
    "failed": N, "skipped_already_done": N}``.

    Candidates are tenders with a non-null `document_url`, not marked
    `Tender.is_restricted`, that either have no `documents` row yet or
    whose `documents` row has `storage_path IS NULL` (i.e. last attempt
    was a failure). Already-completed tenders count toward
    `skipped_already_done` but not toward `limit`.
    """
    summary = {
        "attempted": 0,
        "downloaded": 0,
        "restricted": 0,
        "failed": 0,
        "skipped_already_done": 0,
    }
    settings = get_settings()
    storage_root = Path(settings.dossier_storage_path)
    storage_root.mkdir(parents=True, exist_ok=True)
    timeout = settings.dossier_timeout

    logger.info(
        "Dossier download start: dry_run=%s limit=%s storage=%s",
        dry_run,
        limit,
        storage_root,
    )

    headers = {"User-Agent": _USER_AGENT}
    with get_session() as session, httpx.Client(
        headers=headers, timeout=timeout, follow_redirects=True
    ) as client:
        # Pull all eligible tenders + their current document state in one
        # query; filter in Python so we can distinguish "already done"
        # (counted as skipped) from "needs attempt" (counted via limit).
        candidates = session.execute(
            select(
                Tender.id,
                Tender.ted_notice_id,
                Tender.document_url,
                Document.storage_path,
            )
            .outerjoin(Document, Document.tender_id == Tender.id)
            .where(Tender.document_url.is_not(None))
            .where(Tender.is_restricted.is_(False))
            .order_by(Tender.id)
        ).all()

        for tender_id, ted_notice_id, document_url, existing_storage in candidates:
            if existing_storage is not None:
                summary["skipped_already_done"] += 1
                continue

            if limit is not None and summary["attempted"] >= limit:
                break

            summary["attempted"] += 1
            if verbose:
                logger.info(
                    "Fetching %s for tender %s", document_url, ted_notice_id
                )

            outcome = _process_one(
                session=session,
                tender_id=tender_id,
                ted_notice_id=ted_notice_id,
                url=document_url,
                client=client,
                storage_root=storage_root,
                dry_run=dry_run,
            )
            summary[outcome] += 1

    logger.info(
        "Dossier download complete: %d attempted, %d downloaded, "
        "%d restricted, %d failed, %d skipped (already done)",
        summary["attempted"],
        summary["downloaded"],
        summary["restricted"],
        summary["failed"],
        summary["skipped_already_done"],
    )
    return summary


def _process_one(
    *,
    session: Session,
    tender_id: int,
    ted_notice_id: str,
    url: str,
    client: httpx.Client,
    storage_root: Path,
    dry_run: bool,
) -> str:
    """Process a single tender's download. Returns the summary-key it
    should be counted against (one of: downloaded, restricted, failed,
    skipped_already_done).
    """
    try:
        resp = client.get(url)
    except httpx.TimeoutException as exc:
        logger.warning("Timeout fetching %s: %s", url, exc)
        if not dry_run:
            _upsert_document(
                session,
                tender_id=tender_id,
                source_url=url,
                download_failed=True,
            )
            session.commit()
        return "failed"
    except httpx.HTTPError as exc:
        logger.warning("Error fetching %s: %s", url, exc)
        if not dry_run:
            _upsert_document(
                session,
                tender_id=tender_id,
                source_url=url,
                download_failed=True,
            )
            session.commit()
        return "failed"

    if resp.status_code in (401, 403):
        logger.info("Restricted (%s): %s", resp.status_code, url)
        if not dry_run:
            session.execute(
                update(Tender).where(Tender.id == tender_id).values(is_restricted=True)
            )
            _upsert_document(
                session,
                tender_id=tender_id,
                source_url=url,
                is_restricted=True,
                storage_path=None,
                extracted_text=None,
                download_failed=False,
            )
            session.commit()
        return "restricted"

    if resp.status_code != 200:
        logger.warning("HTTP %s: %s", resp.status_code, url)
        if not dry_run:
            _upsert_document(
                session,
                tender_id=tender_id,
                source_url=url,
                download_failed=True,
            )
            session.commit()
        return "failed"

    body = resp.content
    content_type = resp.headers.get("content-type", "")
    if not _is_pdf_content(content_type, body):
        logger.warning("Non-PDF 200 at %s (content-type=%r)", url, content_type)
        if not dry_run:
            _upsert_document(
                session,
                tender_id=tender_id,
                source_url=url,
                download_failed=True,
            )
            session.commit()
        return "failed"

    sha256 = compute_sha256(body)

    if not dry_run:
        existing = session.execute(
            select(Document.storage_path, Document.extracted_text, Document.downloaded_at)
            .where(Document.file_hash == sha256)
            .where(Document.storage_path.is_not(None))
            .limit(1)
        ).first()
        if existing:
            existing_path, existing_text, existing_downloaded_at = existing
            _upsert_document(
                session,
                tender_id=tender_id,
                source_url=url,
                storage_path=existing_path,
                extracted_text=existing_text,
                file_hash=sha256,
                is_restricted=False,
                download_failed=False,
                downloaded_at=existing_downloaded_at or datetime.utcnow(),
            )
            session.commit()
            return "skipped_already_done"

    storage_path = storage_root / ted_notice_id / f"{sha256[:16]}.pdf"
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        return "downloaded"

    storage_path.write_bytes(body)
    extracted = extract_text_from_pdf(body)
    _upsert_document(
        session,
        tender_id=tender_id,
        source_url=url,
        storage_path=str(storage_path),
        extracted_text=extracted,
        file_hash=sha256,
        is_restricted=False,
        download_failed=False,
        downloaded_at=datetime.utcnow(),
    )
    session.commit()
    return "downloaded"
