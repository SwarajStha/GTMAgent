"""TED Award (CAN) notice back-fill (Job 2).

Walks paginated TED v3 search results for `can-*` notice types, maps each
notice through `AwardRow.from_ted_response`, resolves the winner against
the `companies` table, and upserts into `awards` keyed on `ted_notice_id`.
No LLM calls, no scraping, no fuzzy matching.

Per-notice atomicity is implemented with savepoints so a single malformed
notice doesn't roll back the whole back-fill batch.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Award
from app.db.session import get_session
from app.ingestion.base_client import TedClient
from app.ingestion.entity_resolution import resolve_or_create
from app.ingestion.schemas import AwardRow

logger = logging.getLogger(__name__)


# Response fields requested from TED. Field names verified against the
# "supported values" list TED returned in its first 400 response on
# 2026-05-16 (CLAUDE.md §15, round 1). Several spec-suggested names were
# rejected:
#   winner-name, awarded-value, award-date, n-tenders-received,
#   BT-142-Winner, BT-160-Tender-Value, BT-720-Lot-Tender-Value,
#   BT-1311-Lot-Winner, BT-500-Organisation-name, organisation-name,
#   organisation-country
# Real eForms vocabulary separates `organisation` from `touchpoint` and
# references winners via `winner-touchpoint-*` keys.
AWARD_FIELDS: list[str] = [
    "publication-number",
    "publication-date",
    "notice-type",
    "classification-cpv",
    # Enrichment for ML training (verified populated live 2026-06-16):
    #   notice-title 20/20, description-proc 20/20, procedure-type 20/20,
    #   place-of-performance-subdiv ~13/20, buyer-country-sub 20/20.
    #   winner-identifier/winner-country/BT-720-Tender-Currency 18/20 (already
    #   requested below). See scripts/field_discovery output.
    "notice-title",
    "title-proc",
    "description-proc",
    "description-lot",
    "procedure-type",
    "BT-105-Procedure",
    "place-of-performance-subdiv-proc",
    "place-of-performance-subdiv-lot",
    "buyer-country-sub",
    # Buyer — keep Job-1-proven keys, add structured-org fallbacks.
    "buyer-name",
    "buyer-country",
    "organisation-name-buyer",
    "organisation-country-buyer",
    # Winner — TED stores the winning entity via the touchpoint
    # (contact-point) of the winning organisation. Fallbacks cover the
    # case where the org is recorded as a tendering party.
    "winner-touchpoint-name",
    "winner-touchpoint-partname",
    "winner-identifier",
    "winner-country",
    "tendering-party-name",
    "organisation-name-tenderer",
    "BT-500-Business-European",
    # Award value — BT-720 is awarded contract value; BT-160 is the
    # tender's original offered value (fallback).
    "BT-720-Tender",
    "BT-720-Tender-Currency",
    "BT-160-Tender",
    "BT-160-Tender-Currency",
    # Dates — winner-decision-date when winner was chosen; BT-145 when
    # contract was signed; BT-1451 alternative decision date.
    "winner-decision-date",
    "BT-145-Contract",
    "BT-1451-Contract",
    # Statistics
    "BT-759-LotResult",
    "BT-142-LotResult",
    "links",
]

# `can-desg` is unverified live (see CLAUDE.md §14 — `cn-light` was in docs
# but rejected). If the first smoke 400s with an "unsupported value"
# message, drop `can-desg` (then `can-social` if still failing) and retry.
NOTICE_TYPES = ("can-standard", "can-social", "can-desg")


def _normalise_cpv(code: str) -> str:
    """Strip the EU check-digit suffix: '45000000-7' -> '45000000'."""
    return code.split("-", 1)[0].strip()


def _build_query(cpv_codes: list[str], months: int) -> str:
    since = (datetime.now(timezone.utc) - timedelta(days=months * 30)).strftime(
        "%Y%m%d"
    )
    cpv_list = ", ".join(_normalise_cpv(c) for c in cpv_codes if c)
    notice_types = ", ".join(NOTICE_TYPES)
    # `classification-cpv` is the only CPV field accepted by TED v3 expert
    # search — `cpv-code` and `cpv` both return "field not supported"
    # (proven live during Job 1, CLAUDE.md §14).
    return (
        f"notice-type IN ({notice_types}) "
        f"AND classification-cpv IN ({cpv_list}) "
        f"AND publication-date >= {since}"
    )


def _iter_notices(page: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("notices", "results", "items", "data"):
        v = page.get(key)
        if isinstance(v, list):
            return v
    return []


def _is_no_winner_notice(notice: dict[str, Any]) -> bool:
    """True iff every lot result on this notice is `clos-nw` (closed, no winner).

    These notices are legitimate CAN publications announcing that a
    procurement was cancelled without a contract being awarded. They have
    no winner data by design — separate them from genuine parse errors.
    """
    bt142 = notice.get("BT-142-LotResult")
    if not isinstance(bt142, list) or not bt142:
        return False
    return all(v == "clos-nw" for v in bt142)


def _upsert_award(session: Session, row: AwardRow) -> bool:
    """Insert or update an awards row. Returns True if inserted.

    Distinguishes new vs update via Postgres `xmax = 0` on the returned
    row (same trick as the Job 1 tender upsert in `ted_client.py`).
    """
    values = row.model_dump()
    stmt = pg_insert(Award).values(**values)
    update_cols = {c: stmt.excluded[c] for c in values if c != "ted_notice_id"}
    update_cols["ingested_at"] = sa.func.now()
    stmt = stmt.on_conflict_do_update(
        index_elements=["ted_notice_id"],
        set_=update_cols,
    ).returning(sa.literal_column("(xmax = 0)").label("inserted"))
    return bool(session.execute(stmt).scalar_one())


def _process_notice_persistent(
    session: Session, row: AwardRow
) -> tuple[bool, bool]:
    """Resolve winner + upsert award inside a savepoint.

    Returns (was_inserted, company_was_created). Raises on any error so
    the caller can catch + count + the savepoint auto-rolls-back.
    """
    with session.begin_nested():
        # winner_country is the company's own country (more accurate than the
        # buyer's); identifier (tax id) is the primary dedup key when present.
        company = resolve_or_create(
            session,
            row.winner_raw_name,
            country=row.winner_country or row.buyer_country,
            identifier=row.winner_identifier,
        )
        is_new_company = company.id is None
        session.flush()  # assigns Company.id so we can FK to it
        row.winner_canonical_id = company.id
        inserted = _upsert_award(session, row)
    return inserted, is_new_company


def backfill_awards(
    cpv_codes: list[str],
    backfill_months: int = 24,
    dry_run: bool = False,
    limit: int | None = None,
    verbose: bool = False,
) -> dict[str, int]:
    """Back-fill TED award notices for `cpv_codes` over the last
    `backfill_months` months.

    Returns a summary dict: ``{"fetched": N, "new": N, "updated": N,
    "companies_created": N, "errors": N}``. On `dry_run=True`, no
    database session is opened; only the parse step runs.
    """
    summary = {
        "fetched": 0,
        "new": 0,
        "updated": 0,
        "companies_created": 0,
        "skipped_no_winner": 0,
        "errors": 0,
    }
    query = _build_query(cpv_codes, backfill_months)
    logger.info(
        "Awards backfill start: cpv=%s months=%s dry_run=%s limit=%s",
        cpv_codes,
        backfill_months,
        dry_run,
        limit,
    )

    with TedClient() as client:
        if dry_run:
            _run_dry(client, query, limit, verbose, summary)
        else:
            _run_persist(client, query, limit, verbose, summary)

    logger.info(
        "Backfill complete: %d fetched, %d new, %d updated, %d companies, %d skipped (no winner), %d errors",
        summary["fetched"],
        summary["new"],
        summary["updated"],
        summary["companies_created"],
        summary["skipped_no_winner"],
        summary["errors"],
    )
    return summary


def _run_dry(
    client: TedClient,
    query: str,
    limit: int | None,
    verbose: bool,
    summary: dict[str, int],
) -> None:
    for page in client.search_all_pages(query=query, fields=AWARD_FIELDS):
        for notice in _iter_notices(page):
            if limit is not None and summary["fetched"] >= limit:
                return
            if _is_no_winner_notice(notice):
                summary["skipped_no_winner"] += 1
                continue
            row = _parse_or_count_error(notice, summary, dry=True)
            if row is None:
                continue
            if verbose:
                logger.info(
                    "DRY award id=%s winner=%r value=%s",
                    row.ted_notice_id,
                    row.winner_raw_name,
                    row.contract_value_eur,
                )
            summary["fetched"] += 1


def _run_persist(
    client: TedClient,
    query: str,
    limit: int | None,
    verbose: bool,
    summary: dict[str, int],
) -> None:
    with get_session() as session:
        for page_num, page in enumerate(
            client.search_all_pages(query=query, fields=AWARD_FIELDS), start=1
        ):
            for notice in _iter_notices(page):
                if limit is not None and summary["fetched"] >= limit:
                    session.commit()
                    return
                if _is_no_winner_notice(notice):
                    summary["skipped_no_winner"] += 1
                    continue
                row = _parse_or_count_error(notice, summary, dry=False)
                if row is None:
                    continue
                if verbose:
                    logger.info(
                        "Award id=%s winner=%r value=%s",
                        row.ted_notice_id,
                        row.winner_raw_name,
                        row.contract_value_eur,
                    )
                try:
                    inserted, is_new_company = _process_notice_persistent(
                        session, row
                    )
                except Exception:
                    logger.exception(
                        "Failed to upsert award notice id=%s", row.ted_notice_id
                    )
                    summary["errors"] += 1
                    continue
                summary["fetched"] += 1
                summary["new" if inserted else "updated"] += 1
                if is_new_company:
                    summary["companies_created"] += 1
            # Commit each page so progress is durable + visible, and a late
            # failure doesn't roll back the whole back-fill.
            session.commit()
            logger.info(
                "Page %d committed: fetched=%d new=%d updated=%d companies=%d "
                "skipped_no_winner=%d errors=%d",
                page_num,
                summary["fetched"],
                summary["new"],
                summary["updated"],
                summary["companies_created"],
                summary["skipped_no_winner"],
                summary["errors"],
            )


def _parse_or_count_error(
    notice: dict[str, Any], summary: dict[str, int], dry: bool
) -> AwardRow | None:
    """Run AwardRow.from_ted_response, counting parse failures as errors."""
    try:
        row = AwardRow.from_ted_response(notice)
    except Exception:
        logger.exception(
            "Failed to parse award notice%s", " (dry-run)" if dry else ""
        )
        summary["errors"] += 1
        return None
    if row is None:
        summary["errors"] += 1
        return None
    return row
