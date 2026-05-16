"""Canonical-company lookup for award winners.

Pure string normalisation — lowercase, strip punctuation and common legal
suffixes — then SELECT / INSERT against the `companies` table. No fuzzy
matching, no LLM, no embeddings.

The caller owns the transaction. `resolve_or_create` adds new rows to the
session but does NOT flush or commit. To distinguish "found existing"
from "just inserted", check `company.id is None` BEFORE the caller's
flush — a brand-new Company has no PK yet.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company

logger = logging.getLogger(__name__)


LEGAL_SUFFIXES: Sequence[str] = (
    "gmbh",
    "ag",
    "ltd",
    "llc",
    "sl",
    "spa",
    "bv",
    "nv",
    "sa",
    "oy",
    "ab",
    "as",
    "srl",
    "kft",
    "zrt",
    "aps",
    "aktiengesellschaft",
    "gesellschaft mit beschrankter haftung",
    "limited",
    "incorporated",
    "corporation",
)


# Punctuation we treat as visual decoration in entity names. Deleting (not
# substituting with space) is intentional — "A.B." needs to collapse to "ab",
# not "a b", per the resolution-key tests. Existing whitespace is preserved
# and collapsed separately, so "Co., Ltd." still resolves to "co ltd".
_PUNCT = re.compile(r"[,.&/\\\-]+")
_WS = re.compile(r"\s+")


def normalise_name(raw_name: str) -> str:
    """Produce the resolution key for a company name.

    Steps:
      1. Lowercase, strip outer whitespace.
      2. Delete punctuation `[,.&-/\\]` (adjacent letters fuse).
      3. Collapse internal whitespace.
      4. Strip known legal suffixes from the end, iterating until stable
         (handles stacked suffixes like "Foo GmbH AG").
      5. If the result is empty (input was nothing but a suffix), fall
         back to the lowercased original so we never return "".
    """
    lowered = raw_name.lower().strip()
    s = _PUNCT.sub("", lowered)
    s = _WS.sub(" ", s).strip()
    changed = True
    while changed:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            if s.endswith(" " + suffix):
                s = s[: -(len(suffix) + 1)].rstrip()
                changed = True
                break
            if s == suffix:
                s = ""
                changed = True
                break
    if not s:
        return lowered
    return s


def resolve_or_create(
    session: Session,
    raw_name: str,
    country: str | None = None,
) -> Company:
    """Find or create a canonical `Company` row for `raw_name`.

    On match: appends `raw_name` to `aliases` if not already present.
    On miss: stages a new Company on the session (no flush, no commit).

    The caller owns the transaction. After this returns:
      * `company.id is None` → newly staged (call `session.flush()` to
        assign an id before using it as a FK target).
      * `company.id` is set  → existing row.
    """
    key = normalise_name(raw_name)
    stmt = select(Company).where(Company.resolution_key == key).limit(1)
    existing = session.execute(stmt).scalar_one_or_none()

    if existing is not None:
        aliases = list(existing.aliases or [])
        if raw_name not in aliases:
            aliases.append(raw_name)
            existing.aliases = aliases
        return existing

    company = Company(
        canonical_name=raw_name,
        resolution_key=key,
        aliases=[raw_name],
        country=country,
    )
    session.add(company)
    return company
