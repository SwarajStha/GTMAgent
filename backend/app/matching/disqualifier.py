"""Hard disqualifier rules.

A company is removed from consideration for a tender before any scoring
if it fails any of these gates:
  - missing a mandatory certification
  - operating in an explicitly excluded country
  - below the minimum size threshold required by the buyer
"""
from __future__ import annotations

from app.understanding.schemas import CompanyProfile, TenderProfile


class Disqualifier:
    """Applies the gated disqualification rules to a (tender, company) pair."""

    # TODO: Phase 3 — return (is_disqualified, reasons[])
    def check(self, tender: TenderProfile, company: CompanyProfile) -> tuple[bool, list[str]]:
        ...
