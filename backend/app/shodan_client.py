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


def candidates_for_ports(limit: int) -> list[dict[str, Any]]:
    """Return raw Shodan matches for the ports we care about."""

    matches: list[dict[str, Any]] = []

    # Keep the queries simple; we verify ourselves.
    for q in ("port:8188", "port:11434"):
        matches.extend(shodan_search(q, limit=limit))

    return matches
