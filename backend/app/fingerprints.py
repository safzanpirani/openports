from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .config import settings


def _sanitize_gpu_name(name: str) -> str:
    n = name.strip()

    # Common ComfyUI format: "cuda:0 NVIDIA GeForce RTX 5090 : cudaMallocAsync"
    if n.lower().startswith("cuda:"):
        # drop "cuda:<idx> " prefix
        parts = n.split(" ", 1)
        if len(parts) == 2:
            n = parts[1].strip()

    # Drop allocator suffixes
    for suffix in (": cudaMallocAsync", ": cudaMalloc", ": default"):
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()

    return n


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
                        return _sanitize_gpu_name(first[nk])
            if isinstance(first, str):
                return _sanitize_gpu_name(first)
        if isinstance(val, dict):
            for nk in ("name", "device_name", "model", "product_name"):
                if isinstance(val.get(nk), str):
                    return _sanitize_gpu_name(val[nk])

    # Some builds might just include a string somewhere.
    if isinstance(system_stats.get("gpu_name"), str):
        return _sanitize_gpu_name(system_stats["gpu_name"])

    return None


async def verify_comfyui(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, str | None, dict[str, Any]]:
    """Returns (ok, metadata, models, version, gpu_name, metrics)."""

    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    # 1) system_stats (also gives GPU)
    try:
        r = await client.get(f"{base_url}/system_stats")
        if r.status_code == 200:
            metadata = r.json()
            # Try to infer version (newer ComfyUI nests it under system)
            if isinstance(metadata.get("comfyui_version"), str):
                version = metadata.get("comfyui_version")
            elif isinstance(metadata.get("version"), str):
                version = metadata.get("version")
            else:
                system = metadata.get("system")
                if isinstance(system, dict) and isinstance(system.get("comfyui_version"), str):
                    version = system.get("comfyui_version")
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

    # Calculate metrics
    vram_total_gb = None
    vram_free_gb = None
    ram_total_gb = None
    ram_free_gb = None
    if isinstance(metadata, dict):
        system_obj = metadata.get("system", {})
        if isinstance(system_obj, dict):
            vt = system_obj.get("vram_total")
            vf = system_obj.get("vram_free")
            rt = system_obj.get("ram_total")
            rf = system_obj.get("ram_free")
            if isinstance(vt, (int, float)): vram_total_gb = vt / (1024**3)
            if isinstance(vf, (int, float)): vram_free_gb = vf / (1024**3)
            if isinstance(rt, (int, float)): ram_total_gb = rt / (1024**3)
            if isinstance(rf, (int, float)): ram_free_gb = rf / (1024**3)

    model_count = 0
    if isinstance(models, dict):
        for k, v in models.items():
            if k != "types" and isinstance(v, list):
                model_count += len(v)

    node_count = None
    try:
        r2 = await client.get(f"{base_url}/object_info")
        if r2.status_code == 200:
            node_count = len(r2.json())
    except Exception:
        pass

    metrics = {
        "vram_total_gb": vram_total_gb,
        "vram_free_gb": vram_free_gb,
        "ram_total_gb": ram_total_gb,
        "ram_free_gb": ram_free_gb,
        "model_count": model_count if model_count > 0 else None,
        "node_count": node_count,
        "max_model_params": None,
        "max_context": None
    }

    return ok, metadata, models, version, gpu_name, metrics


async def verify_sdwebui(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, str | None, dict[str, Any]]:
    """Verify a Stable Diffusion WebUI / A1111 / Forge / Vladmandic instance on :7860.

    Returns (ok, metadata, models, version, gpu_name, metrics).
    Distinguishes from ComfyUI (also gradio/7860 sometimes) by hitting the
    A1111-only `/sdapi/v1/options` and `/sdapi/v1/sd-models` endpoints.
    """

    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None
    gpu_name: str | None = None

    try:
        r = await client.get(f"{base_url}/sdapi/v1/options")
        if r.status_code == 200:
            metadata = r.json()
            if isinstance(metadata, dict):
                # A1111 returns commit/version under various keys depending on fork
                for k in ("sd_version", "sd_checkpoint_hash", "version"):
                    if isinstance(metadata.get(k), str):
                        version = metadata[k]
                        break
    except Exception:
        pass

    models_out: dict[str, Any] = {}
    try:
        r = await client.get(f"{base_url}/sdapi/v1/sd-models")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                models_out["sd_models"] = data
    except Exception:
        pass
    try:
        r = await client.get(f"{base_url}/sdapi/v1/loras")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                models_out["loras"] = data
    except Exception:
        pass

    if models_out:
        models = models_out

    ok = metadata is not None or bool(models_out)
    if not ok:
        # Best-effort homepage signature so we still mark "exposed gradio" style hosts.
        try:
            r = await client.get(f"{base_url}/", timeout=settings.HTTP_TIMEOUT_SECONDS)
            if r.status_code == 200:
                t = (r.text or "").lower()
                if "stable diffusion" in t or "automatic1111" in t or "stable-diffusion-webui" in t:
                    ok = True
        except Exception:
            pass

    model_count = 0
    if isinstance(models, dict):
        for v in models.values():
            if isinstance(v, list):
                model_count += len(v)

    metrics = {
        "vram_total_gb": None,
        "vram_free_gb": None,
        "ram_total_gb": None,
        "ram_free_gb": None,
        "model_count": model_count if model_count > 0 else None,
        "node_count": None,
        "max_model_params": None,
        "max_context": None,
    }
    return ok, metadata, models, version, gpu_name, metrics


async def verify_openwebui(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """Verify an Open WebUI instance on :3000 (or wherever).

    Returns (ok, metadata, models, version, metrics). Distinguishes from
    other apps via Open WebUI's `/api/config` and `/api/version` endpoints.
    """

    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/api/config")
        if r.status_code == 200:
            metadata = r.json()
            if isinstance(metadata, dict) and isinstance(metadata.get("version"), str):
                version = metadata["version"]
    except Exception:
        pass

    try:
        r = await client.get(f"{base_url}/api/version")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("version"), str) and not version:
                version = data["version"]
    except Exception:
        pass

    models_out: dict[str, Any] = {}
    try:
        r = await client.get(f"{base_url}/api/models")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                models_out["data"] = data["data"]
            elif isinstance(data, list):
                models_out["data"] = data
    except Exception:
        pass

    if models_out:
        models = models_out

    ok = metadata is not None
    if not ok:
        try:
            r = await client.get(f"{base_url}/")
            if r.status_code == 200:
                t = (r.text or "").lower()
                if "open webui" in t or "openwebui" in t:
                    ok = True
        except Exception:
            pass

    model_count = None
    if isinstance(models, dict) and isinstance(models.get("data"), list):
        model_count = len(models["data"])

    metrics = {
        "vram_total_gb": None,
        "vram_free_gb": None,
        "ram_total_gb": None,
        "ram_free_gb": None,
        "model_count": model_count,
        "node_count": None,
        "max_model_params": None,
        "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_jupyter(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """Verify a Jupyter instance on :8888.

    Returns (ok, metadata, models, version, metrics). `models` reused for
    kernel/notebook listing if accessible. Most exposed Jupyter instances
    require a token, so we treat any "Jupyter Notebook" / "JupyterLab"
    signature as a positive ID even when listings are gated.
    """

    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/api")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("version"), str):
                metadata = data
                version = data["version"]
    except Exception:
        pass

    listing: dict[str, Any] = {}
    try:
        r = await client.get(f"{base_url}/api/kernels")
        if r.status_code == 200:
            kernels = r.json()
            if isinstance(kernels, list):
                listing["kernels"] = kernels
    except Exception:
        pass
    try:
        r = await client.get(f"{base_url}/api/contents")
        if r.status_code == 200:
            contents = r.json()
            if isinstance(contents, dict) and isinstance(contents.get("content"), list):
                listing["root_contents_count"] = len(contents["content"])
    except Exception:
        pass

    if listing:
        models = listing

    ok = metadata is not None
    if not ok:
        try:
            r = await client.get(f"{base_url}/")
            if r.status_code in (200, 302):
                t = (r.text or "").lower()
                if "jupyter" in t:
                    ok = True
                    if "jupyterlab" in t:
                        metadata = {"product": "jupyterlab"}
                    else:
                        metadata = {"product": "jupyter"}
        except Exception:
            pass

    metrics = {
        "vram_total_gb": None,
        "vram_free_gb": None,
        "ram_total_gb": None,
        "ram_free_gb": None,
        "model_count": None,
        "node_count": None,
        "max_model_params": None,
        "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_vllm(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """vLLM exposes OpenAI-compatible /v1/models. Health at /health (200 OK)."""
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/v1/models")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                models = {"data": data["data"]}
                if data.get("object") == "list" and len(data["data"]) > 0:
                    metadata = {"product": "vllm-or-openai-compat"}
    except Exception:
        pass

    try:
        r = await client.get(f"{base_url}/version")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("version"), str):
                version = data["version"]
                metadata = metadata or {}
                if isinstance(metadata, dict):
                    metadata["product"] = "vllm"
    except Exception:
        pass

    ok = metadata is not None
    model_count = None
    if isinstance(models, dict) and isinstance(models.get("data"), list):
        model_count = len(models["data"])
    metrics = {
        "vram_total_gb": None, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": model_count, "node_count": None, "max_model_params": None, "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_tgi(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """HuggingFace Text Generation Inference: /info returns model_id + max_input_length etc."""
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/info")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("model_id"), str):
                metadata = data
                version = data.get("version") if isinstance(data.get("version"), str) else None
                models = {"data": [{"id": data["model_id"]}]}
    except Exception:
        pass

    ok = metadata is not None
    max_context = None
    if isinstance(metadata, dict):
        for k in ("max_total_tokens", "max_input_length"):
            v = metadata.get(k)
            if isinstance(v, int) and (max_context is None or v > max_context):
                max_context = v
    metrics = {
        "vram_total_gb": None, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": 1 if ok else None, "node_count": None,
        "max_model_params": None, "max_context": max_context,
    }
    return ok, metadata, models, version, metrics


async def verify_triton(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """NVIDIA Triton Inference Server: /v2/health/ready and /v2."""
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/v2")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                metadata = data
                version = data.get("version") if isinstance(data.get("version"), str) else None
    except Exception:
        pass

    if metadata is not None:
        try:
            r = await client.post(f"{base_url}/v2/repository/index", json={})
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    models = {"data": data}
        except Exception:
            pass

    ok = metadata is not None
    metrics = {
        "vram_total_gb": None, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": (len(models["data"]) if isinstance(models, dict) and isinstance(models.get("data"), list) else None),
        "node_count": None, "max_model_params": None, "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_ray(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """Ray dashboard: /api/cluster_status and /api/snapshot.

    These reveal the whole cluster — GPU/CPU counts, resources, jobs.
    """
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/api/version")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                version = data.get("ray_version") or data.get("version")
    except Exception:
        pass

    try:
        r = await client.get(f"{base_url}/api/cluster_status")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                metadata = data
    except Exception:
        pass

    ok = metadata is not None
    if not ok:
        try:
            r = await client.get(f"{base_url}/")
            if r.status_code == 200 and "ray" in (r.text or "").lower()[:5000]:
                ok = True
                metadata = {"product": "ray-dashboard"}
        except Exception:
            pass

    # Ray reveals total GPU/CPU resources at the cluster level. Best-effort
    # extraction lives behind a guard since the schema varies between versions.
    vram_total_gb = None
    if isinstance(metadata, dict):
        try:
            data = metadata.get("data") or metadata
            cluster = data.get("clusterStatus") or data
            avail = cluster.get("autoscalerReport", {}).get("clusterStatus", {}) if isinstance(cluster, dict) else {}
            # Just leave vram null — Ray's resource map is keyed by node not by GPU GB.
        except Exception:
            pass

    metrics = {
        "vram_total_gb": vram_total_gb, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": None, "node_count": None, "max_model_params": None, "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_tgwebui(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """oobabooga text-generation-webui API mode: /v1/models (OpenAI-compatible)
    plus /v1/internal/model/info for the loaded model.
    """
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/v1/internal/model/info")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("model_name"), str):
                metadata = data
    except Exception:
        pass

    try:
        r = await client.get(f"{base_url}/v1/models")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                models = {"data": data["data"]}
    except Exception:
        pass

    ok = metadata is not None
    metrics = {
        "vram_total_gb": None, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": (len(models["data"]) if isinstance(models, dict) and isinstance(models.get("data"), list) else None),
        "node_count": None, "max_model_params": None, "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_lmstudio(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """LMStudio server mode (default :1234): OpenAI-compatible /v1/models +
    LMStudio-specific /api/v0/models with extra metadata.
    """
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/api/v0/models")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                models = {"data": data["data"]}
                metadata = {"product": "lmstudio"}
    except Exception:
        pass

    if metadata is None:
        try:
            r = await client.get(f"{base_url}/v1/models")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and isinstance(data.get("data"), list):
                    # OpenAI-compatible — could also be vllm/tgwebui. Use it
                    # as a positive ID only; mark as generic.
                    models = {"data": data["data"]}
                    metadata = {"product": "openai-compat"}
        except Exception:
            pass

    ok = metadata is not None
    metrics = {
        "vram_total_gb": None, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": (len(models["data"]) if isinstance(models, dict) and isinstance(models.get("data"), list) else None),
        "node_count": None, "max_model_params": None, "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_sglang(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """SGLang serving runtime. Default :30000.

    Has OpenAI-compatible /v1/models AND SGLang-specific /get_model_info
    + /get_server_info. The latter discriminates from generic OpenAI-compat.
    """
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/get_model_info")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                metadata = {"product": "sglang", **data}
                if isinstance(data.get("model_path"), str):
                    models = {"data": [{"id": data["model_path"]}]}
    except Exception:
        pass

    try:
        r = await client.get(f"{base_url}/get_server_info")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                if metadata is None:
                    metadata = {"product": "sglang", **data}
                else:
                    metadata.update(data)
                if isinstance(data.get("version"), str):
                    version = data["version"]
    except Exception:
        pass

    ok = metadata is not None
    metrics = {
        "vram_total_gb": None, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": 1 if ok else None, "node_count": None,
        "max_model_params": None, "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_llamacpp(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """llama.cpp `server` binary. Often :8080 or :8000.

    Discriminating endpoints: /props (returns chat_template + system_prompt
    + n_ctx) and /slots. /v1/models is OpenAI-compatible but not unique.
    """
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/props")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and (
                "chat_template" in data or "default_generation_settings" in data
            ):
                metadata = {"product": "llama.cpp", **data}
    except Exception:
        pass

    if metadata is not None:
        try:
            r = await client.get(f"{base_url}/v1/models")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and isinstance(data.get("data"), list):
                    models = {"data": data["data"]}
        except Exception:
            pass

    ok = metadata is not None
    max_context = None
    if isinstance(metadata, dict):
        for k in ("n_ctx_train", "n_ctx", "default_generation_settings"):
            v = metadata.get(k)
            if isinstance(v, int) and (max_context is None or v > max_context):
                max_context = v
            elif isinstance(v, dict):
                inner = v.get("n_ctx") or v.get("n_ctx_train")
                if isinstance(inner, int) and (max_context is None or inner > max_context):
                    max_context = inner
    metrics = {
        "vram_total_gb": None, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": (len(models["data"]) if isinstance(models, dict) and isinstance(models.get("data"), list) else None),
        "node_count": None, "max_model_params": None, "max_context": max_context,
    }
    return ok, metadata, models, version, metrics


async def verify_litellm(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """LiteLLM proxy. Default :4000. /health/liveliness and /v1/models."""
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/health/liveliness")
        if r.status_code == 200:
            metadata = {"product": "litellm"}
    except Exception:
        pass

    if metadata is None:
        try:
            r = await client.get(f"{base_url}/")
            if r.status_code == 200:
                t = (r.text or "")[:5000].lower()
                if "litellm" in t:
                    metadata = {"product": "litellm"}
        except Exception:
            pass

    if metadata is not None:
        try:
            r = await client.get(f"{base_url}/v1/models")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and isinstance(data.get("data"), list):
                    models = {"data": data["data"]}
        except Exception:
            pass

    ok = metadata is not None
    metrics = {
        "vram_total_gb": None, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": (len(models["data"]) if isinstance(models, dict) and isinstance(models.get("data"), list) else None),
        "node_count": None, "max_model_params": None, "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_tensorboard(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """Tensorboard. Default :6006. Signals an active training job nearby."""
    metadata: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    version: str | None = None

    try:
        r = await client.get(f"{base_url}/data/environment")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("version"), str):
                metadata = {"product": "tensorboard", **data}
                version = data["version"]
    except Exception:
        pass

    if metadata is None:
        try:
            r = await client.get(f"{base_url}/data/runs")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    metadata = {"product": "tensorboard"}
                    models = {"data": data}
        except Exception:
            pass

    if metadata is None:
        try:
            r = await client.get(f"{base_url}/")
            if r.status_code == 200 and "tensorboard" in (r.text or "").lower()[:5000]:
                metadata = {"product": "tensorboard"}
        except Exception:
            pass

    ok = metadata is not None
    metrics = {
        "vram_total_gb": None, "vram_free_gb": None, "ram_total_gb": None, "ram_free_gb": None,
        "model_count": None, "node_count": None,
        "max_model_params": None, "max_context": None,
    }
    return ok, metadata, models, version, metrics


async def verify_ollama(base_url: str, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any]]:
    """Returns (ok, metadata, models, version, metrics).
    
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

    model_count = None
    max_params = None
    max_context = None

    if isinstance(models, dict):
        tags = models.get("tags")
        if isinstance(tags, dict) and isinstance(tags.get("models"), list):
            model_count = len(tags["models"])
            
        show_list = models.get("show")
        if isinstance(show_list, list):
            for s in show_list:
                show_data = s.get("show", {})
                
                mi = show_data.get("model_info", {})
                if isinstance(mi, dict):
                    for k, v in mi.items():
                        if "context_length" in k and isinstance(v, (int, float)):
                            if max_context is None or v > max_context:
                                max_context = int(v)
                
                details = show_data.get("details", {})
                if isinstance(details, dict):
                    psize_str = details.get("parameter_size", "")
                    if isinstance(psize_str, str) and psize_str.upper().endswith("B"):
                        try:
                            val = float(psize_str[:-1])
                            if max_params is None or val > max_params:
                                max_params = val
                        except:
                            pass

    metrics = {
        "vram_total_gb": None,
        "vram_free_gb": None,
        "ram_total_gb": None,
        "ram_free_gb": None,
        "model_count": model_count,
        "node_count": None,
        "max_model_params": max_params,
        "max_context": max_context
    }

    return ok, metadata, models, version, metrics

