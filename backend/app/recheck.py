"""Re-fingerprint instances we've seen before, to keep `is_alive` and metadata fresh."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlmodel import Session, select

from .config import settings
from .fingerprints import verify_comfyui, verify_ollama
from .models import Instance, ScanRun, Service
from .scanner import _upsert_instance


async def _verify(client: httpx.AsyncClient, sem: asyncio.Semaphore, inst: Instance) -> tuple[Instance, bool, dict[str, Any]]:
    base_url = f"http://{inst.ip}:{inst.port}"
    async with sem:
        if inst.service == Service.comfyui:
            ok, meta, models, version, gpu_name, metrics = await verify_comfyui(base_url, client)
            return inst, ok, {
                "service": Service.comfyui, "ip": inst.ip, "port": inst.port,
                "ok": ok, "meta": meta, "models": models, "version": version, "gpu_name": gpu_name,
                "shodan_match": inst.shodan, "metrics": metrics,
            }
        else:
            ok, meta, models, version, metrics = await verify_ollama(base_url, client)
            return inst, ok, {
                "service": Service.ollama, "ip": inst.ip, "port": inst.port,
                "ok": ok, "meta": meta, "models": models, "version": version, "gpu_name": None,
                "shodan_match": inst.shodan, "metrics": metrics,
            }


async def run_recheck(
    session: Session,
    *,
    only_stale: bool = True,
    only_alive: bool = False,
    limit: int | None = None,
) -> ScanRun:
    """Re-fingerprint stored instances. Returns a ScanRun with stats.

    `only_stale=True` skips instances whose last_checked_at is fresh enough
    (< RECHECK_STALE_AFTER_MINUTES old). Pass False for a forced full re-check.
    """

    run = ScanRun(source="recheck", query="re-fingerprint", started_at=datetime.utcnow())
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        stmt = select(Instance)
        if only_alive:
            stmt = stmt.where(Instance.is_alive == True)
        if only_stale and settings.RECHECK_STALE_AFTER_MINUTES > 0:
            cutoff = datetime.utcnow() - timedelta(minutes=settings.RECHECK_STALE_AFTER_MINUTES)
            stmt = stmt.where(Instance.last_checked_at <= cutoff)
        # Order so we hit older checks first.
        stmt = stmt.order_by(Instance.last_checked_at.asc())
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        targets = list(session.exec(stmt).all())
        run.candidates = len(targets)
        session.add(run)
        session.commit()

        if not targets:
            run.finished_at = datetime.utcnow()
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

        sem = asyncio.Semaphore(settings.RECHECK_CONCURRENCY)
        timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)
        verified = 0
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            tasks = [_verify(client, sem, t) for t in targets]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                continue
            _inst, ok, payload = r
            if ok:
                verified += 1
            _upsert_instance(
                session,
                payload["service"], payload["ip"], payload["port"], payload["ok"],
                payload["meta"], payload["models"], payload["version"], payload["gpu_name"],
                shodan_match=payload["shodan_match"], metrics=payload["metrics"],
            )

        run.verified = verified
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        session.refresh(run)
        return run
    except Exception as e:
        run.error = str(e)
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        session.refresh(run)
        return run
