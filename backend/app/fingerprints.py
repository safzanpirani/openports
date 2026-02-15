from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .config import settings


def _pick_comfy_gpu_name(system_stats: dict[str, Any] | None) -> str | None:
    if not system_stats:
        return None

    # Field names vary by ComfyUI versions/builds; best-effort extraction.
    for key in ("devices", "gpus", "cuda", "gpu"):
        val = system_stats.get(key)
        if isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, dict):
                for nk in ("name", "device_name", "model", "product_name"):
                    if isinstance(first.get(nk), str):
                        return first[nk]
            if isinstance(first, str):
                return first
        if isinstance(val, dict):
            for nk in ("name", "device_name", "model", "product_name"):
                if isinstance(val.get(nk), str):
                    return val[nk]

    # Some builds might just include a string somewhere.
    if isinstance(system_stats.get("gpu_name"), str):
        return system_stats["gpu_name"]

    return None


async def verify_comfyui(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, str | None]:
    """Returns (ok, metadata, models, version, gpu_name)."""

    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    # 1) system_stats (also gives GPU)
    try:
        r = await client.get(f"{base_url}/system_stats")
        if r.status_code == 200:
            metadata = r.json()
            # Try to infer version
            if isinstance(metadata.get("comfyui_version"), str):
                version = metadata.get("comfyui_version")
            elif isinstance(metadata.get("version"), str):
                version = metadata.get("version")
    except Exception:
        pass

    # 2) models (best-effort)
    models_out: dict[str, Any] = {}
    try:
        r = await client.get(f"{base_url}/models")
        if r.status_code == 200:
            model_types = r.json()
            models_out["types"] = model_types
            if isinstance(model_types, list):
                # Pull a few well-known folders if present
                for folder in ("checkpoints", "loras", "vae", "controlnet"):
                    if folder in model_types:
                        rr = await client.get(f"{base_url}/models/{folder}")
                        if rr.status_code == 200:
                            models_out[folder] = rr.json()
    except Exception:
        pass

    if models_out:
        models = models_out

    # 3) minimal confirmation fallback
    ok = metadata is not None or models is not None
    if not ok:
        try:
            r = await client.get(f"{base_url}/")
            if r.status_code == 200 and "comfy" in (r.text or "").lower():
                ok = True
        except Exception:
            pass

    gpu_name = _pick_comfy_gpu_name(metadata)
    return ok, metadata, models, version, gpu_name


async def verify_ollama(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Returns (ok, metadata, models, version).

    Note: Ollama does NOT reliably expose GPU model info via its HTTP API.
    """

    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    # /api/version
    try:
        r = await client.get(f"{base_url}/api/version")
        if r.status_code == 200:
            metadata = r.json()
            if isinstance(metadata.get("version"), str):
                version = metadata["version"]
    except Exception:
        pass

    # /api/tags + per-model /api/show
    models_out: dict[str, Any] = {}
    try:
        r = await client.get(f"{base_url}/api/tags")
        if r.status_code == 200:
            tags = r.json()
            models_out["tags"] = tags

            items = tags.get("models") if isinstance(tags, dict) else None
            if isinstance(items, list):
                detailed: list[dict[str, Any]] = []
                for item in items[: settings.OLLAMA_SHOW_LIMIT]:
                    name = item.get("name") if isinstance(item, dict) else None
                    if not name:
                        continue
                    try:
                        rr = await client.post(f"{base_url}/api/show", json={"name": name})
                        if rr.status_code == 200:
                            detailed.append({"name": name, "show": rr.json()})
                    except Exception:
                        continue
                if detailed:
                    models_out["show"] = detailed
    except Exception:
        pass

    if models_out:
        models = models_out

    ok = metadata is not None or models is not None
    return ok, metadata, models, version
