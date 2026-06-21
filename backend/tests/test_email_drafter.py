"""Tests for the unified email drafter + validator (G10).

The Claude path is exercised with an injected fake client (no network); the
fallback path is the default (the autouse `_offline_email_drafter` fixture forces
`_llm_available()` False so a populated .env never triggers a real call).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.generation.drafter import EmailDrafter
from app.generation.validator import EmailValidator

SUPPLIER_EVIDENCE = {
    "tender": {
        "ted_notice_id": "T-1",
        "title": "Clinic construction works",
        "buyer_name": "Stadt Wittmund",
        "deadline": None,
    },
    "company": {"name": "Bau GmbH"},
    "score_breakdown": {"final_score": 0.42},
    "match_explanation": "Strong CPV overlap.",
}

BUYER_EVIDENCE = {
    "tender": {"ted_notice_id": "T-2", "title": "Road resurfacing", "buyer_name": "City"},
    "recommended_suppliers": [
        {"name": "Roads SE", "country": "DE", "final_score": 0.6, "explanation": "Roads."},
        {"name": "Bridge AG", "country": "DE", "final_score": 0.5},
    ],
}


def _fake_client(text: str) -> SimpleNamespace:
    """A stand-in for anthropic.Anthropic whose messages.create returns `text`."""
    def create(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    return SimpleNamespace(messages=SimpleNamespace(create=create))


# ── deterministic fallback (default offline path) ───────────────────────────


def test_supplier_fallback_when_llm_unavailable() -> None:
    draft = EmailDrafter().draft(SUPPLIER_EVIDENCE, "supplier")
    assert draft["generator"] == "template"
    assert "Bau GmbH" in draft["subject"]
    assert "Clinic construction works" in draft["subject"]
    assert draft["body"]


def test_buyer_fallback_numbers_each_supplier() -> None:
    draft = EmailDrafter().draft(BUYER_EVIDENCE, "buyer")
    assert draft["generator"] == "template"
    assert "1. Roads SE" in draft["body"]
    assert "2. Bridge AG" in draft["body"]  # enumerated, not all "1."


# ── Claude path (injected fake client) ──────────────────────────────────────


def test_claude_path_parses_json() -> None:
    body = "Hi Bau GmbH team, this is a sufficiently long evidence-grounded body."
    client = _fake_client(f'{{"subject": "Clinic tender", "body": "{body}"}}')
    draft = EmailDrafter(client=client).draft(SUPPLIER_EVIDENCE, "supplier")
    assert draft["generator"] == "claude"
    assert draft["subject"] == "Clinic tender"
    assert draft["body"] == body


def test_claude_path_tolerates_surrounding_prose() -> None:
    client = _fake_client(
        'Sure! Here is the email:\n{"subject": "Hi", "body": '
        '"A long enough body to pass the validator length check."}\nLet me know.'
    )
    draft = EmailDrafter(client=client).draft(SUPPLIER_EVIDENCE, "supplier")
    assert draft["generator"] == "claude"
    assert draft["subject"] == "Hi"


def test_claude_non_json_falls_back_to_template() -> None:
    client = _fake_client("Sorry, I can't produce JSON right now.")
    draft = EmailDrafter(client=client).draft(SUPPLIER_EVIDENCE, "supplier")
    assert draft["generator"] == "template"


def test_claude_invalid_draft_rejected_by_validator() -> None:
    # Empty subject + too-short body → validator fails → fallback.
    client = _fake_client('{"subject": "", "body": "too short"}')
    draft = EmailDrafter(client=client).draft(SUPPLIER_EVIDENCE, "supplier")
    assert draft["generator"] == "template"


# ── validator ───────────────────────────────────────────────────────────────


def test_validator_accepts_well_formed_draft() -> None:
    ok, reasons = EmailValidator().validate({"subject": "Hi", "body": "x" * 50}, {})
    assert ok and reasons == []


def test_validator_rejects_missing_subject_and_short_body() -> None:
    ok, reasons = EmailValidator().validate({"subject": "", "body": "short"}, {})
    assert not ok
    assert "missing subject" in reasons
    assert "body too short" in reasons
