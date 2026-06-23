"""Unit tests for the Understanding-layer FieldExtractor.

The offline path (no client, `_llm_available` patched False by the autouse
`_offline_extractor` fixture) must return a deterministic profile from the base
columns. The Claude path is exercised by injecting a fake client (which bypasses
the offline gate)."""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from app.understanding.extractor import FieldExtractor


class _FakeClient:
    """Minimal stand-in for anthropic.Anthropic returning a fixed JSON payload."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **_kwargs: object) -> SimpleNamespace:
        text = json.dumps(self._payload)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_offline_fallback_uses_base_columns() -> None:
    profile = FieldExtractor().extract_tender(
        "Construction of a clinic with HVAC and electrical works.",
        base={
            "cpv_codes": ["45215130", "45432200"],
            "title": "Clinic construction",
            "buyer_country": "DE",
            "buyer_name": "Stadt Wittmund",
            "budget_eur": 1_200_000.0,
            "deadline": date(2026, 9, 1),
        },
    )
    assert profile.cpv_code == "45215130"  # first CPV
    assert profile.title == "Clinic construction"
    assert profile.buyer_country == "DE"
    assert profile.budget_eur == 1_200_000.0
    assert profile.deadline == date(2026, 9, 1)
    # No LLM → soft fields stay empty.
    assert profile.required_certifications == []
    assert profile.keywords == []


def test_claude_path_enriches_soft_fields() -> None:
    client = _FakeClient(
        {
            "summary": "Clinic construction with HVAC.",
            "required_certifications": ["ISO 9001", "iso 9001", " ISO 14001 "],
            "required_capabilities": ["HVAC installation", "electrical works"],
            "keywords": ["clinic", "hospital"],
            "language": "de",
        }
    )
    profile = FieldExtractor(client=client).extract_tender(
        "raw", base={"cpv_codes": ["45215130"], "title": "Clinic", "buyer_country": "DE"}
    )
    assert profile.summary == "Clinic construction with HVAC."
    # Deduped (case-insensitive) + stripped.
    assert profile.required_certifications == ["ISO 9001", "ISO 14001"]
    assert profile.required_capabilities == ["HVAC installation", "electrical works"]
    assert profile.language == "de"
    # Base column still authoritative.
    assert profile.cpv_code == "45215130"
    assert profile.buyer_country == "DE"


def test_claude_malformed_output_falls_back() -> None:
    bad = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_k: SimpleNamespace(
                content=[SimpleNamespace(type="text", text="not json")]
            )
        )
    )
    profile = FieldExtractor(client=bad).extract_tender(
        "raw", base={"cpv_codes": ["45000000"], "title": "Works"}
    )
    assert profile.title == "Works"
    assert profile.required_certifications == []  # graceful: empty, not a crash


def test_extract_company_offline_and_claude() -> None:
    offline = FieldExtractor().extract_company("raw", base={"name": "Bau GmbH", "country": "DE"})
    assert offline.name == "Bau GmbH"
    assert offline.certifications == []

    client = _FakeClient(
        {
            "description": "Builder.",
            "capabilities": ["road works"],
            "certifications": ["ISO 9001"],
            "languages": ["de"],
        }
    )
    online = FieldExtractor(client=client).extract_company("raw", base={"name": "Bau GmbH"})
    assert online.certifications == ["ISO 9001"]
    assert online.capabilities == ["road works"]
