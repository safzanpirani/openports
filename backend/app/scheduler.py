"""APScheduler wiring for periodic Shodan scans and re-checks."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings


log = logging.getLogger("openports.scheduler")
_scheduler: AsyncIOScheduler | None = None


def _scan_job() -> None:
    from sqlmodel import Session

    from .db import engine
    from .scanner import run_shodan_scan

    log.info("scheduled shodan scan tick")
    try:
        with Session(engine) as s:
            asyncio.run(run_shodan_scan(s))
    except Exception as e:
        log.exception("scheduled shodan scan failed: %s", e)


def _recheck_job() -> None:
    from sqlmodel import Session

    from .db import engine
    from .recheck import run_recheck

    log.info("scheduled recheck tick")
    try:
        with Session(engine) as s:
            asyncio.run(run_recheck(s, only_stale=True))
    except Exception as e:
        log.exception("scheduled recheck failed: %s", e)


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = AsyncIOScheduler()

    if settings.SCAN_INTERVAL_MINUTES > 0:
        _scheduler.add_job(
            _scan_job,
            "interval",
            minutes=settings.SCAN_INTERVAL_MINUTES,
            id="shodan_scan",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        log.info("scheduled shodan scan every %s minute(s)", settings.SCAN_INTERVAL_MINUTES)

    if settings.RECHECK_INTERVAL_MINUTES > 0:
        _scheduler.add_job(
            _recheck_job,
            "interval",
            minutes=settings.RECHECK_INTERVAL_MINUTES,
            id="recheck",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        log.info("scheduled recheck every %s minute(s)", settings.RECHECK_INTERVAL_MINUTES)

    if _scheduler.get_jobs():
        _scheduler.start()
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
