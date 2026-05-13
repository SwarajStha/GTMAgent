"""Application settings loaded from environment variables.

Uses pydantic-settings to parse `.env` and process environment.
All settings are read once and cached via `get_settings()`.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = Field(
        default="postgresql+psycopg://gtm:gtm@localhost:6543/gtm",
        description="Pooled connection used by the FastAPI app at runtime.",
    )
    database_url_direct: str = Field(
        default="postgresql+psycopg://gtm:gtm@localhost:5432/gtm",
        description="Direct connection used by Alembic migrations only.",
    )
    anthropic_api_key: str = Field(default="")
    tavily_api_key: str = Field(default="")
    allowed_cpv_codes: str = Field(
        default="45000000-7,72000000-5,09330000-1",
        description="Comma-separated CPV prefixes to ingest from TED.",
    )
    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    @property
    def cpv_code_list(self) -> list[str]:
        return [c.strip() for c in self.allowed_cpv_codes.split(",") if c.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
