"""APScheduler in-process loop for periodic ingestion + reflection (Job 4 / G13).

Opt-in via ``settings.scheduler_enabled`` (default False) so CI, tests, and a
normal dev/API boot never start polling live TED. When enabled, the FastAPI
lifespan (``app.main``) builds one ``IngestionScheduler``, starts it on startup,
and shuts it down on exit.

Jobs (all cron-scheduled on an in-process ``BackgroundScheduler``, UTC):
  * contracts — daily TED contract-notice poll (``poll_contract_notices``)
  * dossiers  — daily dossier-download sweep (``download_dossiers``)
  * awards    — weekly award-notice back-fill (``backfill_awards``, short lookback)
  * reflect   — daily reflection cycle (``Reflector.reflect`` → auto-retrain + advise)

The job callables are module-level so they can be invoked directly (live smoke,
``run_job_now``, tests) without waiting for the cron trigger. Each opens its own
DB session via the underlying ingestion/reflection function and logs a summary;
APScheduler isolates a failing run so one bad job doesn't tear down the loop.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Stable job ids — used for replace_existing and run_job_now.
JOB_CONTRACTS = "ingest_contracts"
JOB_DOSSIERS = "download_dossiers"
JOB_AWARDS = "ingest_awards"
JOB_REFLECT = "reflect"


# ── job callables (module-level so smoke/tests can invoke them directly) ───────


def job_poll_contracts() -> dict:
    """Daily TED contract-notice poll (live write)."""
    from app.ingestion.ted_client import poll_contract_notices

    settings = get_settings()
    logger.info(
        "scheduler: contract-notice poll starting (days=%s)",
        settings.scheduler_contracts_lookback_days,
    )
    summary = poll_contract_notices(
        cpv_codes=settings.cpv_code_list,
        days=settings.scheduler_contracts_lookback_days,
    )
    logger.info("scheduler: contract-notice poll done: %s", summary)
    return summary


def job_download_dossiers() -> dict:
    """Bulk dossier-download sweep over eligible tenders (live write)."""
    from app.ingestion.dossier_downloader import download_dossiers

    logger.info("scheduler: dossier sweep starting")
    summary = download_dossiers()
    logger.info("scheduler: dossier sweep done: %s", summary)
    return summary


def job_backfill_awards() -> dict:
    """Weekly award-notice back-fill, short catch-up window (live write)."""
    from app.ingestion.awards_client import backfill_awards

    settings = get_settings()
    months = settings.scheduler_awards_lookback_months
    logger.info("scheduler: award back-fill starting (months=%s)", months)
    summary = backfill_awards(
        cpv_codes=settings.cpv_code_list,
        backfill_months=months,
    )
    logger.info("scheduler: award back-fill done: %s", summary)
    return summary


def job_reflect() -> dict:
    """Daily reflection cycle — metrics, feedback-driven retrain, CPV advisory (G9)."""
    from app.agent.reflector import Reflector

    settings = get_settings()
    logger.info("scheduler: reflection cycle starting")
    result = Reflector(min_samples=settings.scheduler_reflection_min_samples).reflect()
    logger.info("scheduler: reflection cycle done: actions=%s", result.get("actions"))
    return result


# Registry independent of enable flags / settings, so run_job_now and tests can
# dispatch any job by id regardless of whether it is scheduled this cycle.
JOB_REGISTRY: dict[str, Callable[[], dict]] = {
    JOB_CONTRACTS: job_poll_contracts,
    JOB_DOSSIERS: job_download_dossiers,
    JOB_AWARDS: job_backfill_awards,
    JOB_REFLECT: job_reflect,
}


class IngestionScheduler:
    """Wraps a ``BackgroundScheduler`` with the ingestion + reflection jobs."""

    def __init__(
        self,
        settings: Settings | None = None,
        scheduler: BackgroundScheduler | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.scheduler = scheduler or BackgroundScheduler(timezone="UTC")

    def _job_specs(self) -> list[tuple[str, Callable[[], dict], str]]:
        """(job_id, callable, cron) for the jobs enabled by settings."""
        s = self.settings
        # (job_id, callable, cron, enabled)
        specs = [
            (JOB_CONTRACTS, job_poll_contracts, s.scheduler_contracts_cron, True),
            (JOB_DOSSIERS, job_download_dossiers, s.scheduler_dossiers_cron,
             s.scheduler_dossiers_enabled),
            (JOB_AWARDS, job_backfill_awards, s.scheduler_awards_cron, True),
            (JOB_REFLECT, job_reflect, s.scheduler_reflection_cron,
             s.scheduler_reflection_enabled),
        ]
        return [(jid, fn, cron) for (jid, fn, cron, enabled) in specs if enabled]

    def register_jobs(self) -> None:
        """Add the enabled jobs to the scheduler (idempotent via replace_existing)."""
        for job_id, fn, cron in self._job_specs():
            self.scheduler.add_job(
                fn,
                trigger=CronTrigger.from_crontab(cron, timezone="UTC"),
                id=job_id,
                name=job_id,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
            )

    def start(self, force: bool = False) -> bool:
        """Register jobs and start the loop. Returns False (no-op) if disabled.

        Safe to call when ``scheduler_enabled`` is False (logs + returns False)
        or when already running (returns False) — so app boot never crashes on it.

        ``force=True`` bypasses the ``scheduler_enabled`` env gate — used by the
        runtime toggle endpoint (G27) so an operator can start the loop at runtime
        without a restart. The env flag still governs *boot* behaviour.
        """
        if not force and not self.settings.scheduler_enabled:
            logger.info("scheduler: disabled (SCHEDULER_ENABLED is false) — not starting")
            return False
        if self.scheduler.running:
            logger.info("scheduler: already running")
            return False
        self.register_jobs()
        self.scheduler.start()
        logger.info(
            "scheduler: started with jobs %s",
            [job.id for job in self.scheduler.get_jobs()],
        )
        return True

    def status(self) -> dict:
        """Snapshot of the loop for the runtime toggle: running + jobs + next runs."""
        running = self.scheduler.running
        jobs = [
            {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in self.scheduler.get_jobs()
        ]
        return {"running": running, "jobs": jobs}

    def shutdown(self, wait: bool = False) -> None:
        """Gracefully stop the loop if it is running."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            logger.info("scheduler: shut down")

    @staticmethod
    def run_job_now(job_id: str) -> dict:
        """Invoke a job's callable immediately (live smoke / manual trigger).

        Bypasses the cron trigger and the enable flags — runs the same code the
        scheduler would. Raises ``KeyError`` for an unknown id.
        """
        try:
            fn = JOB_REGISTRY[job_id]
        except KeyError:
            raise KeyError(f"unknown job id: {job_id!r}; known: {sorted(JOB_REGISTRY)}") from None
        return fn()
