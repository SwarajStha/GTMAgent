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
    database_url_test: str = Field(
        default="postgresql+psycopg://gtm:gtm@localhost:5432/gtm_test",
        description=(
            "Postgres URL used by pytest fixtures. Must point at a separate "
            "database from the dev one — tests TRUNCATE/CREATE/DROP freely. "
            "One-time setup: see backend/scripts/README.md (test DB section)."
        ),
    )
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(
        default="claude-sonnet-4-6",
        description="Claude model id for the email drafter / agent (locked stack).",
    )
    tavily_api_key: str = Field(default="")
    allowed_cpv_codes: str = Field(
        default="45000000-7,72000000-5,09330000-1",
        description="Comma-separated CPV prefixes to ingest from TED.",
    )
    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")
    cors_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated list of browser origins allowed to call the API.",
    )
    dossier_storage_path: str = Field(
        default="./storage/dossiers",
        description="Filesystem root for downloaded tender dossier PDFs.",
    )
    dossier_timeout: int = Field(
        default=30,
        description="Per-request timeout for dossier PDF downloads, in seconds.",
    )
    ted_user_agent: str = Field(
        default="GTMAgent/0.1 (TUM CITHN2014 course project)",
        description="User-Agent sent on every TED API request.",
    )
    ted_request_delay_ms: int = Field(
        default=1000,
        description="Sleep between paginated TED requests, in milliseconds.",
    )
    ted_request_timeout_s: int = Field(
        default=30,
        description="Per-request timeout for TED HTTP calls, in seconds.",
    )
    awards_backfill_months: int = Field(
        default=24,
        description="How many months back to search for TED award notices during back-fill.",
    )

    # ── Scheduler (Job 4 / G13) ───────────────────────────────────────────────
    # The in-process APScheduler loop is OPT-IN. Default False so CI, tests, and a
    # normal dev/API boot never start polling live TED. Enable in production by
    # setting SCHEDULER_ENABLED=true.
    scheduler_enabled: bool = Field(
        default=False,
        description="Start the in-process ingestion/reflection scheduler on app boot.",
    )
    scheduler_contracts_cron: str = Field(
        default="0 3 * * *",
        description="Cron (UTC) for the daily TED contract-notice poll.",
    )
    scheduler_contracts_lookback_days: int = Field(
        default=1,
        description="Day window passed to poll_contract_notices on each scheduled run.",
    )
    scheduler_dossiers_enabled: bool = Field(
        default=True,
        description="Whether the scheduler runs the dossier-download sweep job.",
    )
    scheduler_dossiers_cron: str = Field(
        default="30 3 * * *",
        description="Cron (UTC) for the dossier-download sweep (after the contract poll).",
    )
    scheduler_awards_cron: str = Field(
        default="0 4 * * 1",
        description="Cron (UTC) for the weekly award-notice back-fill.",
    )
    scheduler_awards_lookback_months: int = Field(
        default=1,
        description="Month window for the scheduled award back-fill (catch-up, not the full 24mo).",
    )
    scheduler_reflection_enabled: bool = Field(
        default=True,
        description="Whether the scheduler runs the daily reflection cycle (G9).",
    )
    scheduler_reflection_cron: str = Field(
        default="0 5 * * *",
        description="Cron (UTC) for the daily reflection cycle.",
    )
    scheduler_reflection_min_samples: int = Field(
        default=10,
        description="Min labelled feedback rows before the reflection cycle retrains the LR.",
    )

    @property
    def cpv_code_list(self) -> list[str]:
        return [c.strip() for c in self.allowed_cpv_codes.split(",") if c.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
