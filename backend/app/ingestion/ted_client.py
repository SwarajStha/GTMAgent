"""Client for the EU TED Contract Notices API.

Fetches daily contract notices filtered by the configured CPV codes,
normalises the payload, and writes raw + parsed rows into the `tenders`
table.
"""
from __future__ import annotations


class TEDClient:
    """HTTP client wrapping the TED Contract Notices REST endpoint."""

    def __init__(self, base_url: str = "https://ted.europa.eu/api/v3/notices") -> None:
        self.base_url = base_url

    # TODO: Phase 2 — implement search() against TED, with retry + rate-limit handling
    def search(self, cpv_codes: list[str], since: str | None = None) -> list[dict]:
        ...

    # TODO: Phase 2 — fetch a single notice payload in full
    def fetch_notice(self, notice_id: str) -> dict:
        ...
