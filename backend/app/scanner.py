from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
from sqlmodel import Session, select

from .alerts import evaluate_alerts
from .config import settings
from .enrich_hosting import classify_provider, enrich_ip_hosting
from .fingerprints import (
    verify_comfyui, verify_jupyter, verify_litellm, verify_llamacpp,
    verify_lmstudio, verify_ollama, verify_openwebui, verify_ray,
    verify_sdwebui, verify_sglang, verify_tensorboard, verify_tgi,
    verify_tgwebui, verify_triton, verify_vllm,
)
from .models import Instance, InstanceChange, InstanceCheck, ScanRun, Service
from .models_summary import diff_names, model_names
from .shodan_client import candidates_for_ports
from .telegram import send_telegram_message


def _service_from_port(port: int) -> Service | None:
    """Map a port to its likely (default) service.

    For ports where multiple frameworks collide (8000 = vLLM/Triton, 8080 =
    TGI/llama.cpp/OpenWebUI), the value here is just the *first probe order*
    used by `_verify_one`; if the first probe fails we cascade to the next.
    """
    if port == 8188:
        return Service.comfyui
    if port == 11434:
        return Service.ollama
    if port == 7860:
        return Service.sdwebui
    if port == 3000:
        return Service.openwebui
    if port == 8888:
        return Service.jupyter
    if port == 8000:
        return Service.vllm
    if port == 8080:
        return Service.tgi
    if port == 8265:
        return Service.ray
    if port == 5000:
        return Service.tgwebui
    if port == 1234:
        return Service.lmstudio
    if port == 30000:
        return Service.sglang
    if port == 4000:
        return Service.litellm
    if port == 6006:
        return Service.tensorboard
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
            if port == 7860:
                ok, meta, models, version, gpu_name, metrics = await verify_sdwebui(base_url, client)
                return Service.sdwebui, ip, port, ok, meta, models, version, gpu_name, shodan_compact, metrics
            if port == 3000:
                ok, meta, models, version, metrics = await verify_openwebui(base_url, client)
                return Service.openwebui, ip, port, ok, meta, models, version, None, shodan_compact, metrics
            if port == 8888:
                ok, meta, models, version, metrics = await verify_jupyter(base_url, client)
                return Service.jupyter, ip, port, ok, meta, models, version, None, shodan_compact, metrics
            if port == 8000:
                # 8000 collision: try Triton first (strict /v2 endpoint), then vLLM.
                ok, meta, models, version, metrics = await verify_triton(base_url, client)
                if ok:
                    return Service.triton, ip, port, ok, meta, models, version, None, shodan_compact, metrics
                ok, meta, models, version, metrics = await verify_vllm(base_url, client)
                return Service.vllm, ip, port, ok, meta, models, version, None, shodan_compact, metrics
            if port == 8080:
                # 8080 collision: TGI → llama.cpp → OpenWebUI.
                ok, meta, models, version, metrics = await verify_tgi(base_url, client)
                if ok:
                    return Service.tgi, ip, port, ok, meta, models, version, None, shodan_compact, metrics
                ok, meta, models, version, metrics = await verify_llamacpp(base_url, client)
                if ok:
                    return Service.llamacpp, ip, port, ok, meta, models, version, None, shodan_compact, metrics
                ok, meta, models, version, metrics = await verify_openwebui(base_url, client)
                return Service.openwebui, ip, port, ok, meta, models, version, None, shodan_compact, metrics
            if port == 8265:
                ok, meta, models, version, metrics = await verify_ray(base_url, client)
                return Service.ray, ip, port, ok, meta, models, version, None, shodan_compact, metrics
            if port == 5000:
                ok, meta, models, version, metrics = await verify_tgwebui(base_url, client)
                return Service.tgwebui, ip, port, ok, meta, models, version, None, shodan_compact, metrics
            if port == 1234:
                ok, meta, models, version, metrics = await verify_lmstudio(base_url, client)
                return Service.lmstudio, ip, port, ok, meta, models, version, None, shodan_compact, metrics
            if port == 30000:
                ok, meta, models, version, metrics = await verify_sglang(base_url, client)
                return Service.sglang, ip, port, ok, meta, models, version, None, shodan_compact, metrics
            if port == 4000:
                ok, meta, models, version, metrics = await verify_litellm(base_url, client)
                return Service.litellm, ip, port, ok, meta, models, version, None, shodan_compact, metrics
            if port == 6006:
                ok, meta, models, version, metrics = await verify_tensorboard(base_url, client)
                return Service.tensorboard, ip, port, ok, meta, models, version, None, shodan_compact, metrics

    # unreachable
    raise RuntimeError("unsupported port")


def _upsert_instance(session: Session, service: Service, ip: str, port: int, ok: bool, meta, models, version, gpu_name, shodan_match, metrics: dict[str, Any], discovery_source: str | None = None) -> tuple[Instance, bool]:
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

    if discovery_source:
        srcs = list(inst.discovery_sources or [])
        if discovery_source not in srcs:
            srcs.append(discovery_source)
            inst.discovery_sources = srcs

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
    alive_flipped: bool | None = None
    models_added: list[str] | None = None
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
                alive_flipped = bool(inst.is_alive)
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
                    if d["added"]:
                        models_added = list(d["added"])
        session.commit()
    except Exception:
        session.rollback()

    # Standing alerts. Best-effort; never aborts upsert.
    try:
        evaluate_alerts(
            session, inst,
            is_first_seen=created,
            alive_flipped=alive_flipped,
            models_added=models_added,
        )
    except Exception:
        pass

    return inst, created


async def run_multi_source_scan(
    session: Session,
    *,
    sources: list[str] | None = None,
    limit: int | None = None,
) -> ScanRun:
    """Pull candidates from every configured source, dedupe, fingerprint, upsert.

    Sources without credentials are silently skipped. `sources=None` means
    "all enabled". Pass `["shodan"]` etc. to limit to a subset.
    """
    from . import censys_client, zoomeye_client

    limit = limit or settings.SHODAN_LIMIT
    chosen = sources or ["shodan", "censys", "zoomeye"]

    queried = ", ".join(chosen)
    run = ScanRun(source=f"multi:{queried}", query="port:8188 OR port:11434", started_at=datetime.utcnow())
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        # Each source returns compact-shape dicts with `_source` set.
        gathered: list[dict[str, Any]] = []
        if "shodan" in chosen and settings.SHODAN_API_KEY:
            try:
                for m in candidates_for_ports(limit=limit):
                    if isinstance(m, dict):
                        m.setdefault("_source", "shodan")
                        gathered.append(m)
            except Exception:
                pass
        if "censys" in chosen and censys_client._enabled():
            gathered.extend(censys_client.candidates_for_ports(limit=limit))
        if "zoomeye" in chosen and zoomeye_client._enabled():
            gathered.extend(zoomeye_client.candidates_for_ports(limit=limit))

        # Dedupe by (ip, port) — keep the first (richest) record but union sources.
        by_target: dict[tuple[str, int], dict[str, Any]] = {}
        sources_per_target: dict[tuple[str, int], list[str]] = {}
        for m in gathered:
            ip = m.get("ip_str")
            port = m.get("port")
            if not ip or not isinstance(port, int):
                continue
            key = (ip, port)
            src = m.get("_source") or "unknown"
            sources_per_target.setdefault(key, [])
            if src not in sources_per_target[key]:
                sources_per_target[key].append(src)
            by_target.setdefault(key, m)

        run.candidates = len(by_target)
        session.add(run)
        session.commit()

        sem = asyncio.Semaphore(settings.VERIFY_CONCURRENCY)
        tasks = []
        for (ip, port), m in by_target.items():
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
            service, ip, port, ok, meta, models_v, version, gpu_name, shodan_compact, metrics = r
            if ok:
                verified += 1
            sources = sources_per_target.get((ip, port), [])
            primary_source = sources[0] if sources else "shodan"
            inst, created = _upsert_instance(
                session, service, ip, port, ok, meta, models_v, version, gpu_name,
                shodan_match=shodan_compact, metrics=metrics, discovery_source=primary_source,
            )
            # Add any additional sources beyond the primary one.
            if len(sources) > 1:
                existing = list(inst.discovery_sources or [])
                changed = False
                for s in sources:
                    if s not in existing:
                        existing.append(s)
                        changed = True
                if changed:
                    inst.discovery_sources = existing
                    session.add(inst)
                    session.commit()
            if created and ok:
                new_instances += 1
                await send_telegram_message(
                    f"new {service.value}: {ip}:{port}\nversion={version or 'unknown'} gpu={gpu_name or 'unknown'} via {','.join(sources) or 'shodan'}"
                )

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
            inst, created = _upsert_instance(
                session, service, ip, port, ok, meta, models, version, gpu_name,
                shodan_match=shodan_compact, metrics=metrics, discovery_source="shodan",
            )

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
