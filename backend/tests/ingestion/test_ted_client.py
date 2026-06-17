"""Tests for ingestion.ted_client / base_client / schemas."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.ingestion.base_client import TedClient
from app.ingestion.schemas import TenderRow
from app.ingestion.ted_client import poll_contract_notices


def test_from_ted_response_full() -> None:
    raw = {
        "publication-number": "12345-2026",
        "notice-title": "Construction works for new metro station",
        "buyer-name": "City of Munich",
        "buyer-country": "DE",
        "classification-cpv": ["45000000", "45100000"],
        "deadline-receipt-tender-date-lot": "2026-06-30T17:00:00Z",
        "estimated-value-glo": 1500000.0,
        "estimated-value-cur-glo": "EUR",
        "document-url-lot": "https://ted.europa.eu/notice/12345",
    }
    row = TenderRow.from_ted_response(raw)
    assert row.ted_notice_id == "12345-2026"
    assert row.title == "Construction works for new metro station"
    assert row.buyer_name == "City of Munich"
    assert row.buyer_country == "DE"
    assert row.cpv_codes == ["45000000", "45100000"]
    assert row.deadline is not None and row.deadline.year == 2026
    assert row.budget_eur == 1500000.0
    assert row.currency == "EUR"
    assert row.document_url == "https://ted.europa.eu/notice/12345"
    assert row.status == "active"
    assert row.raw_json == raw


def test_from_ted_response_missing_budget() -> None:
    raw = {
        "publication-number": "67890-2026",
        "notice-title": "IT services",
        "buyer-name": "Some Buyer",
        "buyer-country": "FR",
        "classification-cpv": "72000000",
    }
    row = TenderRow.from_ted_response(raw)
    assert row.budget_eur is None
    assert row.currency is None
    assert row.cpv_codes == ["72000000"]


def test_from_ted_response_fallback_keys() -> None:
    raw = {
        "publication-number": "11111-2026",
        "BT-21-Procedure": "Fallback title via eForms key",
        "buyer-name": "eForms Buyer",
        "buyer-country": "ES",
        "classification-cpv": "45000000",
        "BT-131(d)-Lot": "2026-09-15T12:00:00Z",
    }
    row = TenderRow.from_ted_response(raw)
    assert row.title == "Fallback title via eForms key"
    assert row.buyer_name == "eForms Buyer"
    assert row.buyer_country == "ES"
    assert row.cpv_codes == ["45000000"]
    assert row.deadline is not None and row.deadline.month == 9


def test_search_all_pages_pagination() -> None:
    # ITERATION mode: TED ignores `page`; the only way to advance is to echo
    # the previous response's iterationNextToken back in the request body.
    page1 = {"notices": [{"publication-number": "1"}], "iterationNextToken": "tok-abc"}
    page2 = {"notices": [{"publication-number": "2"}]}  # no token -> stop

    client = TedClient.__new__(TedClient)
    client._user_agent = "test"
    client._timeout_s = 30
    client._page_delay_ms = 0
    mock_session = MagicMock()

    sent_tokens: list[str | None] = []

    def fake_post(path: str, json: dict) -> MagicMock:
        sent_tokens.append(json.get("iterationNextToken"))
        resp = MagicMock()
        resp.status_code = 200
        # Switch on the token the client sent, NOT on `page`.
        resp.json.return_value = page2 if json.get("iterationNextToken") else page1
        return resp

    mock_session.post.side_effect = fake_post
    client._session = mock_session

    pages = list(client.search_all_pages(query="q", fields=["publication-number"]))
    assert pages == [page1, page2]
    assert mock_session.post.call_count == 2
    # First request carries no token; second echoes page1's token back.
    assert sent_tokens == [None, "tok-abc"]


def test_search_all_pages_stops_on_repeated_token() -> None:
    # Regression guard: a non-advancing token (TED bug / our bug) must NOT
    # loop forever. The client stops the second time it sees the same token.
    looping_page = {
        "notices": [{"publication-number": "x"}],
        "iterationNextToken": "stuck",
    }

    client = TedClient.__new__(TedClient)
    client._user_agent = "test"
    client._timeout_s = 30
    client._page_delay_ms = 0
    mock_session = MagicMock()

    def fake_post(path: str, json: dict) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = looping_page  # always the same token
        return resp

    mock_session.post.side_effect = fake_post
    client._session = mock_session

    pages = list(client.search_all_pages(query="q", fields=["publication-number"]))
    # Yields page once, sees "stuck", advances once, sees "stuck" again -> stop.
    assert len(pages) == 2
    assert mock_session.post.call_count == 2


def test_poll_dry_run_no_db_write(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_page = {
        "notices": [
            {
                "publication-number": "abc-2026",
                "notice-title": "T",
                "classification-cpv": "45000000",
            }
        ]
    }

    def fake_search_all(self, query: str, fields: list[str], limit_per_page: int = 100):
        yield fake_page

    monkeypatch.setattr(TedClient, "search_all_pages", fake_search_all)
    monkeypatch.setattr(TedClient, "__enter__", lambda self: self)
    monkeypatch.setattr(TedClient, "__exit__", lambda self, *a: None)

    session_factory = MagicMock()
    monkeypatch.setattr("app.ingestion.ted_client.get_session", session_factory)

    summary = poll_contract_notices(cpv_codes=["45000000"], days=7, dry_run=True)

    assert summary == {"fetched": 1, "new": 0, "updated": 0, "errors": 0}
    assert not session_factory.called
