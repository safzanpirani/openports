from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
from sqlmodel import Session, select

from .config import settings
from .fingerprints import verify_comfyui, verify_ollama
from .models import Instance, ScanRun, Service
from .shodan_client import candidates_for_ports
from .telegram import send_telegram_message


def _service_from_port(port: int) -> Service | None:
    if port == 8188:
        return Service.comfyui
    if port == 11434:
        return Service.ollama
    return None


def _compact_shodan_match(m: dict[str, Any] | None) -> dict[str, Any] | None:
    if not m:
        return None

    compact: dict[str, Any] = {}
    for k in (
        "ip_str",
        "port",
        "org",
        "isp",
        "asn",
        "hostnames",
        "domains",
        "transport",
        "timestamp",
        "product",
        "version",
        "os",
    ):
        if k in m:
            compact[k] = m.get(k)

    loc = m.get("location")
    if isinstance(loc, dict):
        compact["location"] = {
            "country_name": loc.get("country_name"),
            "region_code": loc.get("region_code"),
            "city": loc.get("city"),
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
        }

    return compact


async def _verify_one(
    sem: asyncio.Semaphore,
    ip: str,
    port: int,
    shodan_match: dict[str, Any] | None,
) -> tuple[
    Service,
    str,
    int,
    bool,
    dict[str, Any] | None,
    dict[str, Any] | None,
    str | None,
    str | None,
    dict[str, Any] | None,
]:
    base_url = f"http://{ip}:{port}"
    shodan_compact = _compact_shodan_match(shodan_match)

    async with sem:
        timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            if port == 8188:
                ok, meta, models, version, gpu_name = await verify_comfyui(base_url, client)
                return Service.comfyui, ip, port, ok, meta, models, version, gpu_name, shodan_compact
            if port == 11434:
                ok, meta, models, version = await verify_ollama(base_url, client)
                return Service.ollama, ip, port, ok, meta, models, version, None, shodan_compact

    # unreachable
    raise RuntimeError("unsupported port")


def _upsert_instance(session: Session, service: Service, ip: str, port: int, ok: bool, meta, models, version, gpu_name, shodan_match) -> tuple[Instance, bool]:
    stmt = select(Instance).where(Instance.service == service, Instance.ip == ip, Instance.port == port)
    inst = session.exec(stmt).first()

    created = False
    now = datetime.utcnow()

    if not inst:
        inst = Instance(service=service, ip=ip, port=port)
        created = True

    inst.last_checked_at = now
    inst.is_alive = bool(ok)
    if ok:
        inst.last_seen_at = now
        inst.last_error = None
    else:
        inst.last_error = "verify_failed"

    inst.shodan = shodan_match
    if meta is not None:
        inst.metadata = meta
    if models is not None:
        inst.models = models

    if version:
        inst.version = version
    if gpu_name:
        inst.gpu_name = gpu_name

    session.add(inst)
    session.commit()
    session.refresh(inst)

    return inst, created


async def run_shodan_scan(session: Session, limit: int | None = None) -> ScanRun:
    limit = limit or settings.SHODAN_LIMIT

    run = ScanRun(source="shodan", query="port:8188 OR port:11434", started_at=datetime.utcnow())
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        matches = candidates_for_ports(limit=limit)
        run.candidates = len(matches)
        session.add(run)
        session.commit()

        sem = asyncio.Semaphore(settings.VERIFY_CONCURRENCY)

        tasks = []
        for m in matches:
            ip = m.get("ip_str")
            port = m.get("port")
            if not ip or not isinstance(port, int):
                continue
            service = _service_from_port(port)
            if not service:
                continue
            tasks.append(_verify_one(sem, ip, port, m))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        verified = 0
        new_instances = 0
        for r in results:
            if isinstance(r, Exception):
                continue
            service, ip, port, ok, meta, models, version, gpu_name, shodan_compact = r
            if ok:
                verified += 1
            inst, created = _upsert_instance(session, service, ip, port, ok, meta, models, version, gpu_name, shodan_match=shodan_compact)

            if created and ok:
                new_instances += 1
                await send_telegram_message(f"New {service.value} instance: {ip}:{port}\nversion={version or 'unknown'}\ngpu={gpu_name or 'unknown'}")

        run.verified = verified
        run.new_instances = new_instances
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
