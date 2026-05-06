"""Non-intrusive enrichment for ComfyUI (8188) and Ollama (11434).

Only uses GET/POST endpoints that are part of the public HTTP APIs:
- ComfyUI: GET /system_stats, /models, /models/<type>, /object_info
- Ollama:  GET /api/version, /api/tags, (best-effort) GET /api/ps, POST /api/show

Usage:
  cd backend
  uv run python -m tools.enrich 175.27.130.85 175.231.12.25

Outputs a JSON blob per IP.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx

from app.config import settings
from app.enrich_hosting import enrich_ip_hosting


def _safe_int(v: Any) -> int | None:
    try:
        return int(v)
    except Exception:
        return None


def _bytes_to_gib(b: Any) -> float | None:
    i = _safe_int(b)
    if i is None:
        return None
    return round(i / (1024**3), 2)


async def _get_json(client: httpx.AsyncClient, url: str) -> tuple[int | None, Any | None]:
    try:
        r = await client.get(url)
        return r.status_code, r.json() if r.status_code == 200 else None
    except Exception:
        return None, None


async def _post_json(client: httpx.AsyncClient, url: str, payload: dict[str, Any]) -> tuple[int | None, Any | None]:
    try:
        r = await client.post(url, json=payload)
        return r.status_code, r.json() if r.status_code == 200 else None
    except Exception:
        return None, None


def _extract_comfy_summary(system_stats: dict[str, Any] | None) -> dict[str, Any]:
    if not system_stats:
        return {}

    system = system_stats.get("system") if isinstance(system_stats.get("system"), dict) else system_stats
    devices = system_stats.get("devices") if isinstance(system_stats.get("devices"), list) else []

    gpu0 = devices[0] if devices else None
    if not isinstance(gpu0, dict):
        gpu0 = None

    return {
        "os": system.get("os") if isinstance(system, dict) else None,
        "comfyui_version": system.get("comfyui_version") if isinstance(system, dict) else system_stats.get("comfyui_version"),
        "python_version": system.get("python_version") if isinstance(system, dict) else None,
        "pytorch_version": system.get("pytorch_version") if isinstance(system, dict) else None,
        "ram_total_gib": _bytes_to_gib(system.get("ram_total") if isinstance(system, dict) else system_stats.get("ram_total")),
        "ram_free_gib": _bytes_to_gib(system.get("ram_free") if isinstance(system, dict) else system_stats.get("ram_free")),
        "gpu_name": gpu0.get("name") if gpu0 else None,
        "vram_total_gib": _bytes_to_gib(gpu0.get("vram_total")) if gpu0 else None,
        "vram_free_gib": _bytes_to_gib(gpu0.get("vram_free")) if gpu0 else None,
        "argv": system.get("argv") if isinstance(system, dict) else None,
    }


def _extract_ollama_model_summary(show: dict[str, Any] | None) -> dict[str, Any]:
    if not show:
        return {}

    details = show.get("details") if isinstance(show.get("details"), dict) else {}
    model_info = show.get("model_info") if isinstance(show.get("model_info"), dict) else {}

    # Many models have <family>.context_length in model_info
    ctx = None
    for k, v in model_info.items():
        if isinstance(k, str) and k.endswith(".context_length"):
            ctx = v
            break

    return {
        "family": details.get("family"),
        "parameter_size": details.get("parameter_size"),
        "quantization": details.get("quantization_level"),
        "format": details.get("format"),
        "context_length": ctx,
        "license": show.get("license"),
    }


async def enrich_ip(ip: str) -> dict[str, Any]:
    timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)

    # Hosting enrichment (reverse DNS + provider classification)
    hosting: dict[str, Any] = {}
    try:
        h = await enrich_ip_hosting(ip)
        hosting = {k: v for k, v in h.items() if v}
    except Exception:
        pass

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        out: dict[str, Any] = {"ip": ip, "hosting": hosting, "comfyui": None, "ollama": None}

        # --- ComfyUI ---
        comfy: dict[str, Any] = {}
        status, sysstats = await _get_json(client, f"http://{ip}:8188/system_stats")
        if status == 200 and isinstance(sysstats, dict):
            comfy["system_stats"] = _extract_comfy_summary(sysstats)

            # models
            mstatus, types = await _get_json(client, f"http://{ip}:8188/models")
            if mstatus == 200 and isinstance(types, list):
                comfy["model_types"] = types
                # pull a subset of types for a quick overview (some installations have many types)
                models: dict[str, Any] = {}
                for t in types[:25]:
                    if not isinstance(t, str):
                        continue
                    s, lst = await _get_json(client, f"http://{ip}:8188/models/{t}")
                    if s == 200 and isinstance(lst, list):
                        models[t] = {"count": len(lst), "sample": lst[:5]}
                if models:
                    comfy["models"] = models

            # object_info (node catalog)
            ostatus, obj = await _get_json(client, f"http://{ip}:8188/object_info")
            if ostatus == 200 and isinstance(obj, dict):
                comfy["object_info"] = {
                    "node_count": len(obj.keys()),
                    "sample_nodes": list(obj.keys())[:30],
                }

        if comfy:
            out["comfyui"] = comfy

        # --- Ollama ---
        oll: dict[str, Any] = {}
        vstatus, ver = await _get_json(client, f"http://{ip}:11434/api/version")
        if vstatus == 200 and isinstance(ver, dict):
            oll["version"] = ver.get("version")

            # best-effort: some builds might have it; most won't
            ps_status, ps = await _get_json(client, f"http://{ip}:11434/api/ps")
            if ps_status == 200:
                oll["ps"] = ps

            tstatus, tags = await _get_json(client, f"http://{ip}:11434/api/tags")
            if tstatus == 200 and isinstance(tags, dict):
                items = tags.get("models") if isinstance(tags.get("models"), list) else []
                oll["models"] = {"count": len(items), "names": [m.get("name") for m in items if isinstance(m, dict)][:200]}

                detailed: dict[str, Any] = {}
                for m in items[: settings.OLLAMA_SHOW_LIMIT]:
                    if not isinstance(m, dict):
                        continue
                    name = m.get("name")
                    if not isinstance(name, str):
                        continue
                    s, show = await _post_json(client, f"http://{ip}:11434/api/show", {"name": name})
                    if s == 200 and isinstance(show, dict):
                        detailed[name] = _extract_ollama_model_summary(show)
                if detailed:
                    oll["model_details"] = detailed

        if oll:
            out["ollama"] = oll

        return out


async def main_async(ips: list[str]) -> int:
    sem = asyncio.Semaphore(settings.VERIFY_CONCURRENCY)

    async def _wrap(ip: str):
        async with sem:
            return await enrich_ip(ip)

    results = await asyncio.gather(*[_wrap(ip) for ip in ips])
    for r in results:
        print(json.dumps(r, indent=2, sort_keys=True))
    return 0


def main() -> None:
    ips = [a.strip() for a in sys.argv[1:] if a.strip()]
    if not ips:
        raise SystemExit("Usage: python -m tools.enrich <ip> [ip...] ")

    raise SystemExit(asyncio.run(main_async(ips)))


if __name__ == "__main__":
    main()
