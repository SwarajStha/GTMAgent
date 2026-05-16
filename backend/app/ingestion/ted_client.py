"""TED Contract Notice poller (Job 1).

Builds a CPV/date-bounded query, walks paginated results via `TedClient`,
maps each notice through `TenderRow.from_ted_response`, and upserts into
`tenders` keyed on `ted_notice_id`. No LLM calls, no scraping.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import Tender
from app.db.session import get_session
from app.ingestion.base_client import TedClient
from app.ingestion.schemas import TenderRow

logger = logging.getLogger(__name__)

TED_FIELDS: list[str] = [
    "publication-number",
    "publication-date",
    "notice-title",
    "notice-type",
    "buyer-name",
    "buyer-country",
    "classification-cpv",
    "deadline-receipt-tender-date-lot",
    "deadline-receipt-tender-time-lot",
    "estimated-value-glo",
    "estimated-value-cur-glo",
    "estimated-value-lot",
    "estimated-value-cur-lot",
    "document-url-lot",
    "document-url-part",
    "document-restricted-lot",
    "links",
    "BT-21-Procedure",
    "BT-27-Procedure",
    "BT-27-Procedure-Currency",
    "BT-131(d)-Lot",
]

NOTICE_TYPES = ("cn-standard", "cn-social")


def _normalise_cpv(code: str) -> str:
    """Strip the EU check-digit suffix: '45000000-7' -> '45000000'."""
    return code.split("-", 1)[0].strip()


def _build_query(cpv_codes: list[str], days: int) -> str:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%d")
    cpv_list = ", ".join(_normalise_cpv(c) for c in cpv_codes if c)
    notice_types = ", ".join(NOTICE_TYPES)
    return (
        f"notice-type IN ({notice_types}) "
        f"AND classification-cpv IN ({cpv_list}) "
        f"AND publication-date >= {since}"
    )


def _iter_notices(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the list of notice dicts out of a TED search page response."""
    for key in ("notices", "results", "items", "data"):
        v = page.get(key)
        if isinstance(v, list):
            return v
    return []


def _upsert_tender(session: Any, row: TenderRow) -> bool:
    """Insert or update a tenders row. Returns True if inserted, False if updated.

    Distinguishes new vs update via Postgres `xmax = 0` on the returned row:
    xmax is 0 for a freshly inserted heap tuple, non-zero when ON CONFLICT
    rewrote an existing one.
    """
    values = row.model_dump()
    stmt = pg_insert(Tender).values(**values)
    update_cols = {c: stmt.excluded[c] for c in values if c != "ted_notice_id"}
    update_cols["updated_at"] = sa.func.now()
    stmt = stmt.on_conflict_do_update(
        index_elements=["ted_notice_id"],
        set_=update_cols,
    ).returning(sa.literal_column("(xmax = 0)").label("inserted"))
    return bool(session.execute(stmt).scalar_one())


def poll_contract_notices(
    cpv_codes: list[str],
    days: int = 7,
    dry_run: bool = False,
    limit: int | None = None,
    verbose: bool = False,
) -> dict[str, int]:
    """Poll TED Contract Notices and upsert into the `tenders` table.

    Returns {"fetched": N, "new": N, "updated": N, "errors": N}.
    """
    summary = {"fetched": 0, "new": 0, "updated": 0, "errors": 0}
    query = _build_query(cpv_codes, days)
    logger.info("TED poll start: cpv=%s days=%s dry_run=%s", cpv_codes, days, dry_run)

    with TedClient() as client:
        if dry_run:
            for page in client.search_all_pages(query=query, fields=TED_FIELDS):
                for notice in _iter_notices(page):
                    if limit is not None and summary["fetched"] >= limit:
                        break
                    try:
                        row = TenderRow.from_ted_response(notice)
                        summary["fetched"] += 1
                        if verbose:
                            logger.info(
                                "DRY notice id=%s title=%r",
                                row.ted_notice_id,
                                row.title,
                            )
                    except Exception:
                        logger.exception("Failed to parse notice (dry-run)")
                        summary["errors"] += 1
                if limit is not None and summary["fetched"] >= limit:
                    break
        else:
            with get_session() as session:
                for page in client.search_all_pages(query=query, fields=TED_FIELDS):
                    for notice in _iter_notices(page):
                        if limit is not None and summary["fetched"] >= limit:
                            break
                        try:
                            row = TenderRow.from_ted_response(notice)
                            if verbose:
                                logger.info(
                                    "Notice id=%s title=%r",
                                    row.ted_notice_id,
                                    row.title,
                                )
                            inserted = _upsert_tender(session, row)
                            summary["fetched"] += 1
                            summary["new" if inserted else "updated"] += 1
                        except Exception:
                            logger.exception("Failed to upsert notice")
                            summary["errors"] += 1
                            session.rollback()
                    if limit is not None and summary["fetched"] >= limit:
                        break

    logger.info(
        "Poll complete: %d fetched, %d new, %d updated, %d errors",
        summary["fetched"],
        summary["new"],
        summary["updated"],
        summary["errors"],
    )
    return summary
