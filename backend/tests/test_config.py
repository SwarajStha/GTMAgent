"""Tests for settings parsing helpers."""
from __future__ import annotations

from app.core.config import Settings


def test_cors_origins_list_parses_and_trims() -> None:
    settings = Settings(cors_origins="http://localhost:5173, https://app.example , ")
    assert settings.cors_origins_list == ["http://localhost:5173", "https://app.example"]


def test_cors_origins_list_default_is_local_dev() -> None:
    # _env_file=None ignores any local .env so the documented default is asserted.
    assert Settings(_env_file=None).cors_origins_list == ["http://localhost:5173"]
