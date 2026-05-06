"""Helpers to extract a flat name list from per-service `models` JSON shapes
and to diff two such lists. Keeps the rest of the codebase shape-agnostic.
"""

from __future__ import annotations

from typing import Any, Iterable

from .models import Service


def model_names(service: Service | str, models: dict[str, Any] | None) -> list[str]:
    if not isinstance(models, dict):
        return []

    svc = service.value if isinstance(service, Service) else str(service)

    if svc == "ollama":
        out: list[str] = []
        tags = models.get("tags")
        if isinstance(tags, dict):
            tagged = tags.get("models")
            if isinstance(tagged, list):
                for entry in tagged:
                    if isinstance(entry, dict):
                        name = entry.get("name")
                        if isinstance(name, str):
                            out.append(name)
        return sorted(set(out))

    if svc == "comfyui":
        out = []
        for folder in ("checkpoints", "loras", "vae", "controlnet"):
            arr = models.get(folder)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, str):
                        out.append(f"{folder}/{item}")
        return sorted(set(out))

    return []


def diff_names(before: Iterable[str], after: Iterable[str]) -> dict[str, list[str]]:
    b = set(before)
    a = set(after)
    added = sorted(a - b)
    removed = sorted(b - a)
    return {"added": added, "removed": removed}
