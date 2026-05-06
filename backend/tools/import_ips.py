"""Import IPs into the DB with full enrichment (hosting + service fingerprinting).

Usage:
  cd backend
  uv run python -m tools.import_ips 1.2.3.4 5.6.7.8
  uv run python -m tools.import_ips 1.2.3.4 5.6.7.8 --dry-run

The script:
- runs hosting enrichment (reverse DNS → provider classification)
- runs ComfyUI/Ollama fingerprinting
- upserts into SQLite
- sends Telegram notifications for *new* instances
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

import httpx
from sqlmodel import Session, select

from app.config import settings
from app.db import engine, init_db
from app.enrich_hosting import enrich_ip_hosting
from app.fingerprints import verify_comfyui, verify_ollama
from app.models import Instance, Service
from app.telegram import send_telegram_message


def _from_comfy_meta(meta: dict | None) -> dict:
    """Extract summary metrics from ComfyUI system_stats metadata."""
    out: dict = {}
    if not meta:
        return out

    for dev in meta.get("devices", []) or []:
        if isinstance(dev, dict) and isinstance(dev.get("vram_total"), (int, float)):
            out["vram_total_gb"] = round(dev["vram_total"] / (1024**3), 2)
            if dev.get("vram_free"):
                out["vram_free_gb"] = round(dev["vram_free"] / (1024**3), 2)
            break

    sys = meta.get("system") if isinstance(meta.get("system"), dict) else meta
    for k, v in [("ram_total", "ram_total_gb"), ("ram_free", "ram_free_gb")]:
        if isinstance(sys.get(k), (int, float)):
            out[v] = round(sys[k] / (1024**3), 2)

    return out


def _from_ollama_meta(meta: dict | None, models: dict | None) -> dict:
    """Extract summary metrics from Ollama metadata."""
    out: dict = {}
    if not meta and not models:
        return out

    if models and isinstance(models.get("tags"), dict):
        items = models["tags"].get("models") or []
        if isinstance(items, list):
            out["model_count"] = len(items)
            max_ctx = 0
            max_params = 0.0
            for m in items:
                if not isinstance(m, dict):
                    continue
                d = m.get("details") or {}
                ps = d.get("parameter_size")
                if isinstance(ps, str):
                    try:
                        val = ps.upper()
                        if val.endswith("B"):
                            p = float(val[:-1])
                        elif val.endswith("M"):
                            p = float(val[:-1]) / 1000
                        else:
                            p = float(val)
                        if p > max_params:
                            max_params = p
                    except Exception:
                        pass
                # context comes from model_info not tags; skip here

    return out


async def _import_one(ip: str, dry_run: bool, hosting_only: bool, session: Session) -> list[str]:
    notes: list[str] = []

    # 1) Hosting enrichment
    hosting = await enrich_ip_hosting(ip)
    provider = hosting.get("provider", "unknown")
    ptr = hosting.get("reverse_dns")
    notes.append(f"provider={provider} ptr={ptr or '-'}")

    if hosting_only and not dry_run:
        # Only store a placeholder row for the provider.
        # Both ports — we don't know which side it's on.
        now = datetime.utcnow()
        for port in (8188, 11434):
            svc = Service.comfyui if port == 8188 else Service.ollama
            _do_upsert(session, svc, ip, port, None, None, None, None, provider, ptr, hosting)
        return notes

    timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # 2) ComfyUI
        try:
            ok, meta, models_c, version, gpu_name = await verify_comfyui(f"http://{ip}:8188", client)
            if ok:
                notes.append(f"comfyui ok v={version} gpu={gpu_name}")
                if not dry_run:
                    _do_upsert(session, Service.comfyui, ip, 8188, meta, models_c, version, gpu_name, provider, ptr, hosting)
            elif hosting_only and not dry_run:
                _do_upsert(session, Service.comfyui, ip, 8188, None, None, None, None, provider, ptr, hosting)
        except Exception as e:
            if hosting_only and not dry_run:
                _do_upsert(session, Service.comfyui, ip, 8188, None, None, None, None, provider, ptr, hosting)

        # 3) Ollama
        try:
            ok, meta, models_o, version = await verify_ollama(f"http://{ip}:11434", client)
            if ok:
                notes.append(f"ollama ok v={version}")
                if not dry_run:
                    _do_upsert(session, Service.ollama, ip, 11434, meta, models_o, version, None, provider, ptr, hosting)
            elif hosting_only and not dry_run:
                _do_upsert(session, Service.ollama, ip, 11434, None, None, None, None, provider, ptr, hosting)
        except Exception as e:
            if hosting_only and not dry_run:
                _do_upsert(session, Service.ollama, ip, 11434, None, None, None, None, provider, ptr, hosting)

    return notes


def _do_upsert(session, service, ip, port, meta, models, version, gpu_name, provider, ptr, hosting):
    stmt = select(Instance).where(
        Instance.service == service,
        Instance.ip == ip,
        Instance.port == port,
    )
    inst = session.exec(stmt).first()
    created = False
    now = datetime.utcnow()

    if not inst:
        inst = Instance(service=service, ip=ip, port=port)
        created = True

    inst.last_checked_at = now
    inst.is_alive = True
    inst.last_seen_at = now
    inst.last_error = None
    inst.version = version
    inst.gpu_name = gpu_name
    inst.service_metadata = meta
    inst.models = models
    inst.provider = provider
    inst.reverse_dns = ptr

    # derived metrics
    if service == Service.comfyui:
        d = _from_comfy_meta(meta)
    else:
        d = _from_ollama_meta(meta, models)
    for k, v in d.items():
        try:
            setattr(inst, k, v)
        except Exception:
            pass

    session.add(inst)
    session.commit()
    session.refresh(inst)

    if created:
        note = f"New {service.value}: {ip}:{port} v={version} gpu={gpu_name} provider={provider}"
        asyncio.create_task(send_telegram_message(note))
        print(f"  [NEW] {note}")

    return inst, created


async def main_async(ips: list[str], dry_run: bool, hosting_only: bool) -> int:
    init_db()
    with Session(engine) as session:
        for ip in ips:
            print(f"\n{ip}:")
            notes = await _import_one(ip, dry_run, hosting_only, session)
            for n in notes:
                print(f"  {n}")
    return 0


def main() -> None:
    ips = []
    dry_run = False
    hosting_only = False
    for a in sys.argv[1:]:
        if a.strip() == "--dry-run":
            dry_run = True
        elif a.strip() == "--hosting-only":
            hosting_only = True
        else:
            ips.append(a.strip())

    if not ips:
        raise SystemExit("Usage: python -m tools.import_ips <ip> [ip...] [--dry-run] [--hosting-only]")

    raise SystemExit(asyncio.run(main_async(ips, dry_run, hosting_only)))


if __name__ == "__main__":
    main()
