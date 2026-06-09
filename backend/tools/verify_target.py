"""Verify/fingerprint a single target.

Usage examples:
  cd backend
  uv run python tools/verify_target.py comfyui http://127.0.0.1:18188
  uv run python tools/verify_target.py vllm http://127.0.0.1:8000
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.config import settings
from app.fingerprints import verify_for_service
from app.models import Service


async def _run(service: Service, base_url: str) -> None:
    timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        ok, meta, models, version, gpu_name, metrics = await verify_for_service(service, base_url, client)
        print("ok:", ok)
        print("service:", service.value)
        print("version:", version)
        print("gpu:", gpu_name)
        print("models keys:", list(models.keys()) if isinstance(models, dict) else None)
        print("metadata keys:", list((meta or {}).keys()))
        print("metrics:", metrics)


def main() -> None:
    services = "|".join(s.value for s in Service)
    if len(sys.argv) != 3:
        raise SystemExit(f"Usage: verify_target.py <{services}> <base_url>")

    kind = sys.argv[1].strip()
    service = next((s for s in Service if s.value.lower() == kind.lower()), None)
    if service is None:
        raise SystemExit(f"kind must be one of: {services}")
    base_url = sys.argv[2].strip().rstrip("/")

    asyncio.run(_run(service, base_url))


if __name__ == "__main__":
    main()
