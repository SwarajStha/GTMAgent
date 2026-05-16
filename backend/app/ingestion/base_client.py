"""HTTP wrapper around the TED v3 search API.

Single-purpose: build the request envelope (User-Agent, JSON body), call
the search endpoint, handle non-2xx, and walk pagination. No business
logic — that lives in `ted_client.poll_contract_notices`.
"""
from __future__ import annotations

import logging
import ssl
import time
from collections.abc import Iterator
from types import TracebackType
from typing import Any

import httpx
import truststore

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _build_ssl_context() -> ssl.SSLContext:
    """Use the OS trust store so corporate/AV MITM certs are accepted.

    `certifi` (httpx default) doesn't see CAs installed in Windows' store —
    fine on a clean box, fails on machines with SSL-inspecting AV/proxy.
    """
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class TedClient:
    """Reusable httpx.Client wrapper for the TED v3 search endpoint.

    Per TED ops guidance, two host names serve the same v3 API. We hit the
    primary first; on any transport-level failure (DNS, connect, timeout —
    NOT 4xx/5xx, which we surface) we retry once on the secondary.
    """

    BASE_URL = "https://api.ted.europa.eu/v3"
    SECONDARY_BASE_URL = "https://tedweb.api.ted.europa.eu/v3"
    SEARCH_PATH = "/notices/search"

    def __init__(
        self,
        user_agent: str | None = None,
        timeout_s: int | None = None,
        page_delay_ms: int | None = None,
    ) -> None:
        settings = get_settings()
        self._user_agent = user_agent or settings.ted_user_agent
        self._timeout_s = timeout_s if timeout_s is not None else settings.ted_request_timeout_s
        self._page_delay_ms = (
            page_delay_ms if page_delay_ms is not None else settings.ted_request_delay_ms
        )
        self._session = httpx.Client(
            headers=self._build_headers(),
            timeout=self._timeout_s,
            verify=_build_ssl_context(),
        )

    def _build_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def search(
        self,
        query: str,
        fields: list[str],
        page: int = 1,
        limit: int = 100,
    ) -> dict[str, Any]:
        """POST one page of results from the search endpoint.

        Body fields per TED v3 contract:
          query, fields, page, limit (request shape)
          scope=ACTIVE (filter to live notices)
          checkQuerySyntax=false (we already validate upstream)
          paginationMode=ITERATION (pairs with iterationNextToken in resp)
        """
        body = {
            "query": query,
            "fields": fields,
            "page": page,
            "limit": limit,
            "scope": "ACTIVE",
            "checkQuerySyntax": False,
            "paginationMode": "ITERATION",
        }
        logger.debug("TED search page=%s limit=%s query=%s", page, limit, query)
        last_transport_err: httpx.TransportError | None = None
        for idx, base in enumerate((self.BASE_URL, self.SECONDARY_BASE_URL)):
            url = base + self.SEARCH_PATH
            try:
                resp = self._session.post(url, json=body)
            except httpx.TransportError as exc:
                last_transport_err = exc
                logger.warning("TED transport error on %s: %s", base, exc)
                continue
            if idx > 0:
                logger.warning("TED search succeeded on secondary host %s", base)
            if resp.status_code // 100 != 2:
                logger.error(
                    "TED search failed: status=%s body=%s",
                    resp.status_code,
                    resp.text[:2000],
                )
                resp.raise_for_status()
            return resp.json()
        assert last_transport_err is not None
        raise last_transport_err

    def search_all_pages(
        self,
        query: str,
        fields: list[str],
        limit_per_page: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """Yield each page of results. Sleeps between requests, stops when
        the response has no `nextPage` token."""
        page = 1
        while True:
            data = self.search(query=query, fields=fields, page=page, limit=limit_per_page)
            yield data
            next_token = (
                data.get("iterationNextToken")
                or data.get("nextPage")
                or data.get("next-page")
                or data.get("nextPageToken")
            )
            if not next_token:
                return
            page += 1
            if self._page_delay_ms > 0:
                time.sleep(self._page_delay_ms / 1000.0)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "TedClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
