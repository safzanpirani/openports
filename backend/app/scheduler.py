"""APScheduler wiring for periodic multi-source scans and re-checks."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings


log = logging.getLogger("openports.scheduler")
_scheduler: AsyncIOScheduler | None = None


def _scan_job() -> None:
    """Run one scheduled scan across every enabled source.

    AsyncIOScheduler runs this sync function in the event loop's default thread
    pool, so we own a fresh event loop here via ``asyncio.run`` and the sync
    source clients block this worker thread, not the API's event loop.
    """
    from sqlmodel import Session

    from .db import engine
    from .scanner import run_multi_source_scan

    sources = settings.scan_sources_list
    log.info("scheduled scan tick (sources=%s)", ",".join(sources) if sources else "all-enabled")
    try:
        with Session(engine) as s:
            run = asyncio.run(run_multi_source_scan(s, sources=sources))
        log.info(
            "scheduled scan done: candidates=%s verified=%s new=%s error=%s",
            run.candidates, run.verified, run.new_instances, run.error,
        )
    except Exception as e:
        log.exception("scheduled scan failed: %s", e)


def _recheck_job() -> None:
    from sqlmodel import Session

    from .db import engine
    from .recheck import run_recheck

    log.info("scheduled recheck tick")
    try:
        with Session(engine) as s:
            run = asyncio.run(run_recheck(s, only_stale=True))
        log.info(
            "scheduled recheck done: candidates=%s verified=%s error=%s",
            run.candidates, run.verified, run.error,
        )
    except Exception as e:
        log.exception("scheduled recheck failed: %s", e)


def _on_job_event(event) -> None:  # noqa: ANN001
    if event.code == EVENT_JOB_MISSED:
        log.warning(
            "scheduler: job '%s' missed its run time (event loop busy) — "
            "raise SCHEDULER_MISFIRE_GRACE_SECONDS if this recurs", event.job_id,
        )
    elif event.code == EVENT_JOB_MAX_INSTANCES:
        log.warning(
            "scheduler: job '%s' skipped — previous run still in progress", event.job_id,
        )
    elif event.code == EVENT_JOB_ERROR:
        log.error("scheduler: job '%s' raised: %s", event.job_id, event.exception)


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    grace = max(1, settings.SCHEDULER_MISFIRE_GRACE_SECONDS)
    _scheduler = AsyncIOScheduler(
        job_defaults={
            # Never silently drop a delayed tick; collapse backed-up runs into one.
            "misfire_grace_time": grace,
            "coalesce": True,
            "max_instances": 1,
        }
    )
    _scheduler.add_listener(
        _on_job_event,
        EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES,
    )

    if settings.SCAN_INTERVAL_MINUTES > 0:
        _scheduler.add_job(
            _scan_job,
            "interval",
            minutes=settings.SCAN_INTERVAL_MINUTES,
            id="scan",
            replace_existing=True,
        )
        log.info("scheduled scan every %s minute(s)", settings.SCAN_INTERVAL_MINUTES)

    if settings.RECHECK_INTERVAL_MINUTES > 0:
        _scheduler.add_job(
            _recheck_job,
            "interval",
            minutes=settings.RECHECK_INTERVAL_MINUTES,
            id="recheck",
            replace_existing=True,
        )
        log.info("scheduled recheck every %s minute(s)", settings.RECHECK_INTERVAL_MINUTES)

    if _scheduler.get_jobs():
        _scheduler.start()
        for job in _scheduler.get_jobs():
            log.info("scheduler: job '%s' next run at %s", job.id, job.next_run_time)
    else:
        log.info("scheduler: no jobs registered (both intervals are 0)")
    return _scheduler


def get_scheduler_status() -> dict:
    """Snapshot of the scheduler for /api/stats — running flag + next run times."""
    status: dict = {"running": bool(_scheduler is not None and _scheduler.running), "jobs": {}}
    if _scheduler is not None:
        for job in _scheduler.get_jobs():
            nrt = job.next_run_time
            status["jobs"][job.id] = nrt.isoformat() if nrt else None
    return status


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
