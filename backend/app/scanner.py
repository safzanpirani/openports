from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
from sqlmodel import Session, select

from .config import settings
from .enrich_hosting import classify_provider, enrich_ip_hosting
from .fingerprints import verify_comfyui, verify_ollama
from .models import Instance, InstanceChange, InstanceCheck, ScanRun, Service
from .models_summary import diff_names, model_names
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
    dict[str, Any],
]:
    base_url = f"http://{ip}:{port}"
    shodan_compact = _compact_shodan_match(shodan_match)

    async with sem:
        timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            if port == 8188:
                ok, meta, models, version, gpu_name, metrics = await verify_comfyui(base_url, client)
                return Service.comfyui, ip, port, ok, meta, models, version, gpu_name, shodan_compact, metrics
            if port == 11434:
                ok, meta, models, version, metrics = await verify_ollama(base_url, client)
                return Service.ollama, ip, port, ok, meta, models, version, None, shodan_compact, metrics

    # unreachable
    raise RuntimeError("unsupported port")


def _upsert_instance(session: Session, service: Service, ip: str, port: int, ok: bool, meta, models, version, gpu_name, shodan_match, metrics: dict[str, Any]) -> tuple[Instance, bool]:
    stmt = select(Instance).where(Instance.service == service, Instance.ip == ip, Instance.port == port)
    inst = session.exec(stmt).first()

    created = False
    now = datetime.utcnow()

    # Snapshot pre-state so we can diff after writing
    pre_alive = None if not inst else inst.is_alive
    pre_version = None if not inst else inst.version
    pre_gpu = None if not inst else inst.gpu_name
    pre_models = model_names(service, inst.models if inst else None)

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
        inst.service_metadata = meta
    if models is not None:
        inst.models = models

    # Provider enrichment from Shodan compact data + reverse DNS
    if shodan_match and not inst.provider:
        asn = shodan_match.get("asn")
        org = shodan_match.get("org")
        isp = shodan_match.get("isp")
        inst.provider = classify_provider(asn=asn, shodan_org=org, shodan_isp=isp)

    if version:
        inst.version = version
    if gpu_name:
        inst.gpu_name = gpu_name

    for f in ("vram_total_gb", "vram_free_gb", "ram_total_gb", "ram_free_gb", "model_count", "max_model_params", "max_context", "node_count"):
        val = metrics.get(f)
        if val is not None:
            setattr(inst, f, val)

    session.add(inst)
    session.commit()
    session.refresh(inst)

    # Append a check row + any change rows. Best-effort; never abort the upsert.
    try:
        check = InstanceCheck(
            instance_id=inst.id,
            checked_at=now,
            is_alive=inst.is_alive,
            version=inst.version,
            gpu_name=inst.gpu_name,
            vram_total_gb=inst.vram_total_gb,
            vram_free_gb=inst.vram_free_gb,
            model_count=inst.model_count,
            max_model_params=inst.max_model_params,
            max_context=inst.max_context,
            error=inst.last_error,
        )
        session.add(check)

        if created:
            session.add(InstanceChange(
                instance_id=inst.id, at=now, kind="first_seen",
                before=None, after={"alive": inst.is_alive, "version": inst.version, "gpu": inst.gpu_name},
            ))
        else:
            if pre_alive is not None and pre_alive != inst.is_alive:
                session.add(InstanceChange(
                    instance_id=inst.id, at=now, kind="alive_changed",
                    before={"alive": pre_alive}, after={"alive": inst.is_alive},
                ))
            if pre_version != inst.version and inst.version:
                session.add(InstanceChange(
                    instance_id=inst.id, at=now, kind="version_changed",
                    before={"version": pre_version}, after={"version": inst.version},
                ))
            if pre_gpu != inst.gpu_name and inst.gpu_name:
                session.add(InstanceChange(
                    instance_id=inst.id, at=now, kind="gpu_changed",
                    before={"gpu": pre_gpu}, after={"gpu": inst.gpu_name},
                ))
            if models is not None:
                post_models = model_names(service, inst.models)
                d = diff_names(pre_models, post_models)
                if d["added"] or d["removed"]:
                    session.add(InstanceChange(
                        instance_id=inst.id, at=now, kind="models_changed",
                        before={"count": len(pre_models)},
                        after={"count": len(post_models), **d},
                    ))
        session.commit()
    except Exception:
        session.rollback()

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
        seen_targets: set[tuple[str, int]] = set()
        for m in matches:
            ip = m.get("ip_str")
            port = m.get("port")
            if not ip or not isinstance(port, int):
                continue
            service = _service_from_port(port)
            if not service:
                continue
            target = (ip, port)
            if target in seen_targets:
                continue
            seen_targets.add(target)
            tasks.append(_verify_one(sem, ip, port, m))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        verified = 0
        new_instances = 0
        for r in results:
            if isinstance(r, Exception):
                continue
            service, ip, port, ok, meta, models, version, gpu_name, shodan_compact, metrics = r
            if ok:
                verified += 1
            inst, created = _upsert_instance(session, service, ip, port, ok, meta, models, version, gpu_name, shodan_match=shodan_compact, metrics=metrics)

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
