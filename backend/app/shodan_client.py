from __future__ import annotations

from typing import Any, Dict, List

import shodan

from .config import settings


def shodan_search(query: str, limit: int) -> list[dict[str, Any]]:
    if not settings.SHODAN_API_KEY:
        raise RuntimeError("SHODAN_API_KEY is not set")

    api = shodan.Shodan(settings.SHODAN_API_KEY)
    res = api.search(query, limit=limit)
    return list(res.get("matches", []))


SUPPORTED_PORTS = (
    8188,   # comfyui
    11434,  # ollama
    7860,   # sdwebui / a1111 / forge
    3000,   # openwebui
    8888,   # jupyter
    8000,   # vllm / triton
    8080,   # tgi / llama.cpp / openwebui (alt)
    8265,   # ray dashboard
    5000,   # text-generation-webui
    1234,   # lmstudio
    30000,  # sglang
    4000,   # litellm
    6006,   # tensorboard
    8317,   # CLIProxyAPI
)


def candidates_for_ports(limit: int, ports: tuple[int, ...] = SUPPORTED_PORTS) -> list[dict[str, Any]]:
    """Return raw Shodan matches for the ports we care about."""

    matches: list[dict[str, Any]] = []

    # Keep the queries simple; we verify ourselves.
    for port in ports:
        matches.extend(shodan_search(f"port:{port}", limit=limit))

    return matches
