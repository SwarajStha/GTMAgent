"""Client for the EU TED Award Notices API used for historical back-fill.

Used both for cold-start data and as a downstream signal for the matching
model (who actually won past contracts in each CPV category).
"""
from __future__ import annotations


class AwardsClient:
    """HTTP client wrapping the TED Award Notices REST endpoint."""

    def __init__(self, base_url: str = "https://ted.europa.eu/api/v3/notices") -> None:
        self.base_url = base_url

    # TODO: Phase 2 — implement back-fill query for award notices
    def search_awards(self, cpv_codes: list[str], years_back: int = 3) -> list[dict]:
        ...
