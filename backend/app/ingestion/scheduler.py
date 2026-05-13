"""APScheduler setup for periodic ingestion jobs.

Schedules:
  - daily TED contract notice pull
  - weekly award notice back-fill
  - on-demand dossier download
"""
from __future__ import annotations


class IngestionScheduler:
    """Wraps an APScheduler BackgroundScheduler with the ingestion jobs."""

    def __init__(self) -> None:
        ...

    # TODO: Phase 2 — register daily/weekly jobs and start the scheduler
    def start(self) -> None:
        ...

    # TODO: Phase 2 — gracefully shut down on app teardown
    def shutdown(self) -> None:
        ...
