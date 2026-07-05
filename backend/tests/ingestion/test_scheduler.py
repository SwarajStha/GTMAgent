"""Tests for the in-process ingestion/reflection scheduler (Job 4 / G13).

TED-free: job registration + lifecycle are asserted via APScheduler's
introspection; the one dispatch test monkeypatches the underlying ingestion
function so nothing hits the network or the DB.
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.ingestion import scheduler as sched
from app.ingestion.scheduler import (
    JOB_AWARDS,
    JOB_CONTRACTS,
    JOB_DOSSIERS,
    JOB_REFLECT,
    IngestionScheduler,
)


def _settings(**overrides) -> Settings:
    """Settings with the scheduler explicitly configured (ignores .env drift)."""
    base = dict(
        scheduler_enabled=True,
        scheduler_dossiers_enabled=True,
        scheduler_reflection_enabled=True,
    )
    base.update(overrides)
    return Settings(**base)


def test_disabled_start_is_noop() -> None:
    s = IngestionScheduler(settings=_settings(scheduler_enabled=False))
    assert s.start() is False
    assert s.scheduler.running is False
    assert s.scheduler.get_jobs() == []


def test_force_start_bypasses_env_gate() -> None:
    # G27: the runtime toggle can start the loop even when SCHEDULER_ENABLED is off.
    s = IngestionScheduler(settings=_settings(scheduler_enabled=False))
    try:
        assert s.start(force=True) is True
        assert s.scheduler.running is True
        status = s.status()
        assert status["running"] is True
        assert len(status["jobs"]) >= 1
    finally:
        s.shutdown()
    assert s.scheduler.running is False


def test_status_reports_not_running_before_start() -> None:
    s = IngestionScheduler(settings=_settings())
    status = s.status()
    assert status["running"] is False
    assert status["jobs"] == []


def test_register_jobs_adds_all_four() -> None:
    s = IngestionScheduler(settings=_settings())
    s.register_jobs()
    ids = {job.id for job in s.scheduler.get_jobs()}
    assert ids == {JOB_CONTRACTS, JOB_DOSSIERS, JOB_AWARDS, JOB_REFLECT}


def test_register_jobs_respects_disable_flags() -> None:
    s = IngestionScheduler(
        settings=_settings(scheduler_dossiers_enabled=False, scheduler_reflection_enabled=False)
    )
    s.register_jobs()
    ids = {job.id for job in s.scheduler.get_jobs()}
    assert ids == {JOB_CONTRACTS, JOB_AWARDS}


def test_register_jobs_is_idempotent_when_running() -> None:
    # replace_existing dedups against the jobstore once the scheduler is running
    # (pre-start jobs are pending, not yet deduped). start() itself only
    # registers once and no-ops on a second call, so this is the realistic path.
    s = IngestionScheduler(settings=_settings())
    try:
        s.start()
        s.register_jobs()  # replace_existing=True → no duplicates
        assert len(s.scheduler.get_jobs()) == 4
    finally:
        s.shutdown()


def test_start_then_shutdown_lifecycle() -> None:
    s = IngestionScheduler(settings=_settings())
    try:
        assert s.start() is True
        assert s.scheduler.running is True
        assert len(s.scheduler.get_jobs()) == 4
        # Cron triggers are daily/weekly — nothing fires during the test.
        assert s.start() is False  # already running → no-op
    finally:
        s.shutdown()
    assert s.scheduler.running is False


def test_run_job_now_dispatches_to_underlying(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_poll(*, cpv_codes, days):
        calls["cpv_codes"] = cpv_codes
        calls["days"] = days
        return {"new": 0, "updated": 0}

    # job_poll_contracts imports poll_contract_notices from this module at call time.
    monkeypatch.setattr("app.ingestion.ted_client.poll_contract_notices", fake_poll)

    result = IngestionScheduler.run_job_now(JOB_CONTRACTS)
    assert result == {"new": 0, "updated": 0}
    assert "cpv_codes" in calls and "days" in calls


def test_run_job_now_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        IngestionScheduler.run_job_now("does_not_exist")


def test_job_registry_covers_all_ids() -> None:
    assert set(sched.JOB_REGISTRY) == {JOB_CONTRACTS, JOB_DOSSIERS, JOB_AWARDS, JOB_REFLECT}
