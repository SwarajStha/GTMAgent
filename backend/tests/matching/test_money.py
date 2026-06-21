"""Unit tests for EUR currency normalisation (G7, pure)."""
from __future__ import annotations

import pytest

from app.matching.money import to_eur


def test_eur_passthrough() -> None:
    assert to_eur(100_000, "EUR") == 100_000.0


def test_converts_known_currency() -> None:
    assert to_eur(100, "PLN") == pytest.approx(23.0)
    assert to_eur(1000, "czk") == pytest.approx(40.0)  # case-insensitive


def test_sentinels_are_dropped() -> None:
    assert to_eur(-1, "EUR") is None
    assert to_eur(0, "EUR") is None


def test_unknown_or_missing_currency_is_none() -> None:
    assert to_eur(100, "XYZ") is None
    assert to_eur(100, None) is None
    assert to_eur(100, "") is None


def test_non_numeric_value_is_none() -> None:
    assert to_eur(None, "EUR") is None
    assert to_eur("not-a-number", "EUR") is None


def test_numeric_string_value_is_accepted() -> None:
    assert to_eur("250", "EUR") == 250.0
