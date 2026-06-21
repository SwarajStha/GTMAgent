"""Canonical-company lookup for award winners.

Resolution is identifier-first: match on the winner's tax/registration id
(TED `winner-identifier`) when present, else fall back to name normalisation
— lowercase, strip punctuation and common legal suffixes. Then SELECT /
INSERT against the `companies` table. No fuzzy matching, no LLM, no
embeddings.

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


_MIN_IDENTIFIER_DIGITS = 4


def clean_identifier(raw: str | None) -> str | None:
    """Normalise a TED `winner-identifier` into a usable dedup key, or None.

    TED data carries junk in this field that, if trusted, would *false-merge*
    unrelated companies onto a shared sentinel — far worse than a missed
    merge. Observed live: all-zero placeholders (`"0"`) and TEXTUAL
    placeholders like `"keine Angabe"` / `"n/a"`. We reject anything without
    at least `_MIN_IDENTIFIER_DIGITS` digits: real tax/registration ids and
    TED's GUID-style org ids are digit-heavy (`A28472819`, `HRB131774`,
    `DE811234567`), textual placeholders are not. The full stripped string is
    kept as the key (exact-match only) — we deliberately do NOT strip prefixes
    like `"NIP:"`, since over-normalising risks the false merges we're
    avoiding. A prefixed vs bare id is a *missed* merge, which is safe.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if sum(c.isdigit() for c in s) < _MIN_IDENTIFIER_DIGITS:
        return None
    if set(s) <= {"0"}:  # all zeros, regardless of length
        return None
    return s


def _append_alias(company: Company, raw_name: str) -> None:
    aliases = list(company.aliases or [])
    if raw_name not in aliases:
        aliases.append(raw_name)
        company.aliases = aliases


def resolve_or_create(
    session: Session,
    raw_name: str,
    country: str | None = None,
    identifier: str | None = None,
) -> Company:
    """Find or create a canonical `Company` row for a winning organisation.

    Matching precedence:
      1. By `identifier` (tax/registration id) when present and non-junk —
         the stable key. A hit merges, even across variant spellings.
      2. By normalised name (`resolution_key`) otherwise.

    When an id is supplied but only a name match is found:
      * existing row has no id        → backfill the id onto it (same entity,
        first time we learned its id), then merge.
      * existing row has a *different* id → distinct legal entity sharing a
        trading name → create a NEW row (a deliberate split; this is why the
        name/key unique indexes were relaxed in migration 0008).

    On any match: appends `raw_name` to `aliases` if new.
    On miss: stages a new Company (no flush, no commit — caller owns the txn).
    After return: `company.id is None` ⇒ newly staged; else existing.
    """
    key = normalise_name(raw_name)
    ident = clean_identifier(identifier)

    if ident is not None:
        by_id = session.execute(
            select(Company).where(Company.registration_id == ident).limit(1)
        ).scalar_one_or_none()
        if by_id is not None:
            _append_alias(by_id, raw_name)
            return by_id

        by_name = session.execute(
            select(Company).where(Company.resolution_key == key).limit(1)
        ).scalar_one_or_none()
        if by_name is not None and by_name.registration_id is None:
            # Same entity, first id we've seen for it — backfill and merge.
            by_name.registration_id = ident
            _append_alias(by_name, raw_name)
            return by_name
        # by_name has a different id (distinct entity) or no name match:
        # fall through to create a new row carrying this id.
        company = Company(
            canonical_name=raw_name,
            resolution_key=key,
            registration_id=ident,
            aliases=[raw_name],
            country=country,
        )
        session.add(company)
        return company

    # No usable identifier — name-only resolution (legacy behaviour).
    existing = session.execute(
        select(Company).where(Company.resolution_key == key).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        _append_alias(existing, raw_name)
        return existing

    company = Company(
        canonical_name=raw_name,
        resolution_key=key,
        aliases=[raw_name],
        country=country,
    )
    session.add(company)
    return company
