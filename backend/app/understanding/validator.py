"""Post-extraction validation and repair.

Catches the typical extraction failures (malformed CPV, sentinel/implausible
budget, a deadline already in the past, dirty list fields) and either repairs the
value in place or records an issue string. `validate_tender` returns
``(ok, issues)`` where ``ok`` is False only on a *blocking* problem (an unusable
CPV code); softer problems (past deadline, dropped budget) are repaired and
reported as non-blocking issues so the profile is still usable downstream.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from app.understanding.schemas import TenderProfile

# A budget above this (EUR) is almost certainly an un-converted/sentinel value
# rather than a real contract estimate — drop it rather than trust it.
_MAX_PLAUSIBLE_BUDGET_EUR = 1e11


def _clean_list(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


class ExtractionValidator:
    """Sanity-checks (and repairs) an extracted profile."""

    def validate_tender(
        self, profile: TenderProfile, raw_text: str = ""
    ) -> tuple[bool, list[str]]:
        """Validate + repair `profile` in place. Return ``(ok, issues)``."""
        issues: list[str] = []
        blocking = False

        # CPV — must be a 6-8 digit numeric code (check digit / dots / spaces ok).
        digits = re.sub(r"\D", "", profile.cpv_code or "")
        if not digits:
            issues.append("missing CPV code")
            blocking = True
        elif len(digits) < 6:
            issues.append(f"CPV code too short: {profile.cpv_code!r}")
            blocking = True
        else:
            profile.cpv_code = digits[:8].ljust(8, "0")

        # Budget — drop non-positive sentinels (-1/0) and implausible magnitudes.
        if profile.budget_eur is not None:
            if profile.budget_eur <= 0:
                issues.append(f"dropped non-positive budget {profile.budget_eur}")
                profile.budget_eur = None
            elif profile.budget_eur > _MAX_PLAUSIBLE_BUDGET_EUR:
                issues.append(f"dropped implausible budget {profile.budget_eur}")
                profile.budget_eur = None

        # Deadline — repair-free, but flag a past deadline (tender likely closed).
        if profile.deadline is not None and profile.deadline < datetime.now(UTC).date():
            issues.append(f"deadline already passed: {profile.deadline.isoformat()}")

        # List fields — defensive dedupe/strip (the extractor already cleans, but
        # a fallback/hand-built profile may not).
        profile.required_certifications = _clean_list(profile.required_certifications)
        profile.required_capabilities = _clean_list(profile.required_capabilities)
        profile.keywords = _clean_list(profile.keywords)

        # Title — backfill a placeholder rather than block on it.
        if not (profile.title or "").strip():
            issues.append("missing title")
            profile.title = "(untitled tender)"

        return (not blocking, issues)
