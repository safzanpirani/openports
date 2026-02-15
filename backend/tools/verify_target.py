"""Verify/fingerprint a single target.

Usage examples:
  cd backend
  uv run python tools/verify_target.py comfyui http://127.0.0.1:18188
  uv run python tools/verify_target.py ollama http://127.0.0.1:11435
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.config import settings
from app.fingerprints import verify_comfyui, verify_ollama


async def _run(kind: str, base_url: str) -> None:
    timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        if kind == "comfyui":
            ok, meta, models, version, gpu_name = await verify_comfyui(base_url, client)
            print("ok:", ok)
            print("version:", version)
            print("gpu:", gpu_name)
            print("models keys:", list(models.keys()) if isinstance(models, dict) else None)
            print("metadata keys:", list((meta or {}).keys()))
            return

        if kind == "ollama":
            ok, meta, models, version = await verify_ollama(base_url, client)
            print("ok:", ok)
            print("version:", version)
            if isinstance(models, dict):
                tags = models.get("tags")
                items = tags.get("models") if isinstance(tags, dict) else None
                print("model count:", len(items) if isinstance(items, list) else None)
                show = models.get("show")
                print("show count:", len(show) if isinstance(show, list) else None)
            print("metadata:", meta)
            return

        raise SystemExit("kind must be comfyui or ollama")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: verify_target.py <comfyui|ollama> <base_url>")

    kind = sys.argv[1].strip().lower()
    base_url = sys.argv[2].strip().rstrip("/")

    asyncio.run(_run(kind, base_url))


if __name__ == "__main__":
    main()
