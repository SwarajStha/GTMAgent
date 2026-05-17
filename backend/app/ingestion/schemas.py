"""Pydantic schemas for the ingestion layer.

`TenderRow` mirrors the columns of the `tenders` table. `from_ted_response`
maps a single TED v3 notice payload into the internal shape, tolerating
schema drift between the v3 legacy keys and the eForms BT-XXX keys.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class TenderRow(BaseModel):
    """One row of the `tenders` table, pre-DB."""

    model_config = ConfigDict(extra="ignore")

    ted_notice_id: str
    title: str | None = None
    buyer_name: str | None = None
    buyer_country: str | None = None
    cpv_codes: list[str] = Field(default_factory=list)
    deadline: datetime | None = None
    budget_eur: float | None = None
    currency: str | None = None
    status: str = "active"
    document_url: str | None = None
    raw_json: dict[str, Any]

    @classmethod
    def from_ted_response(cls, raw: dict[str, Any]) -> "TenderRow":
        """Build a TenderRow from a single TED v3 notice dict.

        Tries the primary key first, then each fallback in order. Logs a
        WARNING if none of the alternatives is populated. Never raises on a
        missing optional field — stores None instead.

        Note on lot flattening: TED's Search API is notice-based, not
        lot-based — when a notice has multiple lots, per-lot budgets,
        CPVs, and deadlines come back flattened into top-level lists with
        no reliable lot-to-value mapping. Convention here:
          - budget_eur: first numeric value (`_amount_from` recurses into
            list[0]); rest stay in `raw_json`.
          - cpv_codes:  ALL values, deduped (a tender genuinely covers
            multiple CPV categories at once).
          - deadline:   earliest parseable date among the values (that's
            the binding submission cut-off).
        This is a TED API structural limitation, not a parsing bug.
        """
        notice_id = _pick(raw, "publication-number", warn_on_miss=True)
        if not notice_id:
            raise ValueError("TED notice missing publication-number (required)")

        return cls(
            ted_notice_id=str(notice_id),
            title=_pick_str(raw, "notice-title", "BT-21-Procedure"),
            buyer_name=_pick_str(raw, "buyer-name"),
            buyer_country=_pick_str(raw, "buyer-country"),
            cpv_codes=_pick_cpv_list(raw, "classification-cpv"),
            deadline=_pick_datetime(
                raw, "deadline-receipt-tender-date-lot", "BT-131(d)-Lot"
            ),
            budget_eur=_pick_amount(
                raw,
                "BT-27-Procedure",
                "estimated-value-glo",
                "estimated-value-lot",
            ),
            currency=_pick_str(
                raw,
                "BT-27-Procedure-Currency",
                "estimated-value-cur-glo",
                "estimated-value-cur-lot",
            ),
            document_url=_pick_str(
                raw,
                "document-url-lot",
                "document-url-part",
                warn_on_miss=False,
            )
            or _doc_url_from_links(raw.get("links")),
            raw_json=raw,
        )


def _doc_url_from_links(links: Any) -> str | None:
    """Extract a canonical document URL from TED's `links` envelope.

    Shape: {"pdf": {"ENG": "...", "DEU": "...", ...}, "xml": {"MUL": "..."}}.
    Prefer English PDF, then any PDF, then the XML.
    """
    if not isinstance(links, dict):
        return None
    for kind in ("pdf", "pdfs", "html"):
        bucket = links.get(kind)
        if isinstance(bucket, dict):
            for lang in ("ENG", "eng"):
                v = bucket.get(lang)
                if isinstance(v, str):
                    return v
            for v in bucket.values():
                if isinstance(v, str):
                    return v
    xml = links.get("xml")
    if isinstance(xml, dict):
        for v in xml.values():
            if isinstance(v, str):
                return v
    return None


def _pick(
    raw: dict[str, Any],
    primary: str,
    *fallbacks: str,
    warn_on_miss: bool = True,
) -> Any:
    """Return the first non-None value among primary + fallbacks, or None.

    Warns when none of the alternative keys is populated (only if at least
    one fallback was provided — a single-key lookup is considered optional).
    """
    for key in (primary, *fallbacks):
        if raw.get(key) is not None:
            return raw[key]
    if warn_on_miss and fallbacks:
        logger.warning(
            "TED notice missing all of %s (notice id=%s)",
            ", ".join(repr(k) for k in (primary, *fallbacks)),
            raw.get("publication-number", "<unknown>"),
        )
    return None


_LANG_PREF = ("eng", "ENG", "en", "EN")


def _pick_str(
    raw: dict[str, Any],
    primary: str,
    *fallbacks: str,
    warn_on_miss: bool = True,
) -> str | None:
    val = _pick(raw, primary, *fallbacks, warn_on_miss=warn_on_miss)
    return _str_from(val)


def _str_from(val: Any) -> str | None:
    """Unwrap a string out of TED's many value shapes.

    Handles: plain str, list[str], list[dict], multilingual dict like
    {"eng": ["..."], "deu": ["..."]}, and dicts with value/text/name keys.
    """
    if val is None:
        return None
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        for lang in _LANG_PREF:
            if lang in val:
                inner = _str_from(val[lang])
                if inner is not None:
                    return inner
        for k in ("value", "text", "en", "name"):
            if k in val:
                inner = _str_from(val[k])
                if inner is not None:
                    return inner
        for v in val.values():
            inner = _str_from(v)
            if inner is not None:
                return inner
        return None
    if isinstance(val, list) and val:
        return _str_from(val[0])
    return str(val)


def _pick_cpv_list(raw: dict[str, Any], primary: str, *fallbacks: str) -> list[str]:
    val = _pick(raw, primary, *fallbacks, warn_on_miss=False)
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    raw_list: list[str] = []
    if isinstance(val, list):
        for item in val:
            if isinstance(item, str):
                raw_list.append(item)
            elif isinstance(item, dict):
                code = item.get("code") or item.get("value")
                if isinstance(code, str):
                    raw_list.append(code)
    elif isinstance(val, dict):
        code = val.get("code") or val.get("value")
        if isinstance(code, str):
            raw_list.append(code)
    seen: set[str] = set()
    deduped: list[str] = []
    for c in raw_list:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    return deduped


def _pick_datetime(raw: dict[str, Any], primary: str, *fallbacks: str) -> datetime | None:
    """Return the earliest parseable datetime among the picked value(s).

    TED flattens lot-level dates into a single list at the notice level (no
    lot-to-value mapping). For deadlines we want the *earliest* — that's
    the binding submission cut-off if there are multiple lots.
    """
    val = _pick(raw, primary, *fallbacks)
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    candidates: list[str] = []
    if isinstance(val, list):
        for item in val:
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                inner = item.get("value") or item.get("date")
                if isinstance(inner, str):
                    candidates.append(inner)
    elif isinstance(val, dict):
        inner = val.get("value") or val.get("date")
        if isinstance(inner, str):
            candidates.append(inner)
    elif isinstance(val, str):
        candidates.append(val)
    parsed: list[datetime] = []
    for s in candidates:
        try:
            parsed.append(datetime.fromisoformat(s.replace("Z", "+00:00")))
        except ValueError:
            logger.warning("Unparseable date %r in field %r", s, primary)
    return min(parsed) if parsed else None


def _amount_from(val: Any) -> float | None:
    """Pull a numeric amount out of TED's estimated-value shapes."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, list) and val:
        return _amount_from(val[0])
    if isinstance(val, dict):
        for k in ("amount", "value", "amount-eur"):
            if k in val:
                return _amount_from(val[k])
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _pick_amount(raw: dict[str, Any], primary: str, *fallbacks: str) -> float | None:
    return _amount_from(_pick(raw, primary, *fallbacks))


class DocumentRow(BaseModel):
    """One row of the `documents` table, pre-DB.

    Mirrors the Job-3 `Document` model. Populated by `dossier_downloader`
    after attempting (and possibly completing) a PDF download.
    """

    model_config = ConfigDict(extra="ignore")

    tender_id: int
    source_url: str
    storage_path: str | None = None
    extracted_text: str | None = None
    is_restricted: bool = False
    download_failed: bool = False
    file_hash: str | None = None
    downloaded_at: datetime | None = None


class AwardRow(BaseModel):
    """One row of the `awards` table, pre-DB.

    `winner_canonical_id` is populated by the entity-resolution step in
    `awards_client.backfill_awards`, not by `from_ted_response` — the FK
    target row may not exist yet at parse time.
    """

    model_config = ConfigDict(extra="ignore")

    ted_notice_id: str
    cpv_code: str | None = None
    buyer_name: str | None = None
    buyer_country: str | None = None
    winner_raw_name: str
    winner_canonical_id: int | None = None
    contract_value_eur: float | None = None
    award_date: date | None = None
    n_offers_received: int | None = None
    raw_json: dict[str, Any]

    @classmethod
    def from_ted_response(cls, raw: dict[str, Any]) -> "AwardRow | None":
        """Map a single TED Award (CAN) notice payload into an AwardRow.

        Returns None (and logs WARNING) when a *required* field is absent
        after all fallbacks — `publication-number` or `winner_raw_name`.
        For optional fields, drift-tolerant lookup: try the primary key
        first, then each fallback in order; if all are absent, log
        WARNING and store None.

        Same lot-flattening caveat as `TenderRow.from_ted_response`:
        TED's Search API is notice-based, not lot-based. Multi-lot
        notices flatten lot values into top-level lists with no reliable
        lot-to-value mapping. Convention here is "take first element" —
        a TED structural limitation, not a parsing bug.
        """
        notice_id = raw.get("publication-number")
        if not notice_id:
            logger.warning("Award notice missing publication-number; skipping")
            return None
        notice_id = str(notice_id)

        # Winner name. Round-2 live evidence (notice 82677-2026 et al,
        # 2026-05-16): on selec-w notices, `organisation-name-tenderer` is
        # always populated (as a multilingual dict). `tendering-party-name`
        # is sometimes also present (flat list). `winner-touchpoint-name`
        # is in the supported-fields list but never populated in practice.
        winner = _str_from(
            _award_first(
                raw,
                "organisation-name-tenderer",
                "tendering-party-name",
                "winner-touchpoint-name",
                "winner-touchpoint-partname",
                notice_id=notice_id,
                field_label="winner_raw_name",
            )
        )
        if not winner:
            logger.warning(
                "Award notice %s missing winner_raw_name; skipping", notice_id
            )
            return None

        # BT-720 is awarded contract value; BT-160 is the tender's
        # original offered value (often equal, sometimes not).
        value_raw = _award_first(
            raw,
            "BT-720-Tender",
            "BT-160-Tender",
            notice_id=notice_id,
            field_label="contract_value_eur",
        )
        contract_value_eur = _to_float(value_raw)

        # `winner-decision-date` is when the winner was chosen;
        # `BT-145-Contract` is when the contract was concluded (signed).
        # `BT-1451-Contract` is an alternative encoding of the decision date.
        date_raw = _award_first(
            raw,
            "winner-decision-date",
            "BT-145-Contract",
            "BT-1451-Contract",
            notice_id=notice_id,
            field_label="award_date",
        )
        award_date = _to_iso_date(date_raw)

        n_offers_raw = _award_first(
            raw,
            "BT-759-LotResult",
            notice_id=notice_id,
            field_label="n_offers_received",
            warn_on_miss=False,
        )
        n_offers_received = _to_int(n_offers_raw)

        cpv_val = _award_first(
            raw,
            "classification-cpv",
            notice_id=notice_id,
            field_label="cpv_code",
            warn_on_miss=False,
        )
        cpv_code = _str_from(cpv_val)

        buyer_name = _str_from(
            _award_first(
                raw,
                "buyer-name",
                "organisation-name-buyer",
                notice_id=notice_id,
                field_label="buyer_name",
                warn_on_miss=False,
            )
        )
        buyer_country = _str_from(
            _award_first(
                raw,
                "buyer-country",
                "organisation-country-buyer",
                notice_id=notice_id,
                field_label="buyer_country",
                warn_on_miss=False,
            )
        )

        return cls(
            ted_notice_id=notice_id,
            cpv_code=cpv_code,
            buyer_name=buyer_name,
            buyer_country=buyer_country,
            winner_raw_name=winner,
            contract_value_eur=contract_value_eur,
            award_date=award_date,
            n_offers_received=n_offers_received,
            raw_json=raw,
        )


def _award_first(
    raw: dict[str, Any],
    *keys: str,
    notice_id: str = "<unknown>",
    field_label: str = "?",
    warn_on_miss: bool = True,
) -> Any:
    """Award-specific key lookup. Returns the first non-None value among
    `keys`, taking `list[0]` if a list (the TED multi-lot flattening
    convention). Logs a WARNING with notice-id context if all keys are
    absent (suppressible)."""
    for key in keys:
        v = raw.get(key)
        if v is None:
            continue
        if isinstance(v, list):
            if not v:
                continue
            return v[0]
        return v
    if warn_on_miss:
        logger.warning(
            "Award %s: %s missing — none of %s present",
            notice_id,
            field_label,
            ", ".join(repr(k) for k in keys),
        )
    return None


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val))
    except (TypeError, ValueError):
        return None


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    try:
        return int(str(val))
    except (TypeError, ValueError):
        return None


def _to_iso_date(val: Any) -> date | None:
    """Parse an ISO date (YYYY-MM-DD or longer with time suffix) to `date`."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if not isinstance(val, str):
        return None
    # Accept YYYY-MM-DD plus full ISO datetimes — take the date part.
    try:
        return date.fromisoformat(val[:10])
    except ValueError:
        return None
