"""Scan one or more IPs for ComfyUI (8188) and Ollama (11434) and print fingerprints.

This is an *authorized* testing helper.

Usage:
  cd backend
  uv run python tools/scan_ips.py 175.27.130.85 175.231.12.25

Or via stdin:
  printf "175.27.130.85\n175.231.12.25\n" | uv run python tools/scan_ips.py -
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Iterable

import httpx

from app.config import settings
from app.fingerprints import verify_comfyui, verify_ollama


@dataclass
class Result:
    ip: str
    service: str
    ok: bool
    version: str | None = None
    gpu: str | None = None
    model_count: int | None = None
    notes: str | None = None


def _iter_ips(argv: list[str]) -> list[str]:
    if len(argv) >= 2 and argv[1] == "-":
        return [line.strip() for line in sys.stdin if line.strip()]
    return [a.strip() for a in argv[1:] if a.strip()]


async def _scan_one(ip: str, client: httpx.AsyncClient) -> list[Result]:
    out: list[Result] = []

    # ComfyUI
    try:
        ok, meta, models, version, gpu_name = await verify_comfyui(f"http://{ip}:8188", client)
        model_count = None
        if isinstance(models, dict):
            cps = models.get("checkpoints")
            if isinstance(cps, list):
                model_count = len(cps)
        out.append(Result(ip=ip, service="comfyui", ok=ok, version=version, gpu=gpu_name, model_count=model_count))
    except Exception as e:
        out.append(Result(ip=ip, service="comfyui", ok=False, notes=str(e)))

    # Ollama
    try:
        ok, meta, models, version = await verify_ollama(f"http://{ip}:11434", client)
        model_count = None
        if isinstance(models, dict):
            tags = models.get("tags")
            items = tags.get("models") if isinstance(tags, dict) else None
            if isinstance(items, list):
                model_count = len(items)
        out.append(Result(ip=ip, service="ollama", ok=ok, version=version, gpu=None, model_count=model_count))
    except Exception as e:
        out.append(Result(ip=ip, service="ollama", ok=False, notes=str(e)))

    return out


async def main_async(ips: Iterable[str]) -> int:
    timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)
    limits = httpx.Limits(max_connections=settings.VERIFY_CONCURRENCY)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, limits=limits) as client:
        sem = asyncio.Semaphore(settings.VERIFY_CONCURRENCY)

        async def _wrapped(ip: str):
            async with sem:
                return await _scan_one(ip, client)

        results_nested = await asyncio.gather(*[_wrapped(ip) for ip in ips])

    results = [r for sub in results_nested for r in sub]

    # Pretty-ish print
    for r in results:
        status = "OK" if r.ok else "NO"
        extra = []
        if r.version:
            extra.append(f"v={r.version}")
        if r.gpu:
            extra.append(f"gpu={r.gpu}")
        if r.model_count is not None:
            extra.append(f"models={r.model_count}")
        if r.notes and not r.ok:
            extra.append(f"err={r.notes}")
        print(f"{r.ip} {r.service:7} {status} " + (" ".join(extra) if extra else ""))

    return 0


def main() -> None:
    ips = _iter_ips(sys.argv)
    if not ips:
        raise SystemExit("Provide IPs as args, or '-' to read from stdin")

    raise SystemExit(asyncio.run(main_async(ips)))


if __name__ == "__main__":
    main()
