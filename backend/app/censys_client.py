"""Censys Search v2 candidate fetcher.

Uses HTTP Basic auth via CENSYS_API_ID + CENSYS_API_SECRET. Each candidate
returned has the same compact shape as the Shodan compact match so the rest
of the pipeline can treat them uniformly:

    {
        "ip_str": str,
        "port": int,
        "org": str | None,
        "isp": str | None,
        "asn": int | None,
        "hostnames": list[str],
        "domains": list[str],
        "transport": "tcp",
        "timestamp": str | None,
        "product": None,
        "version": None,
        "os": None,
        "location": {country_name, region_code, city, latitude, longitude},
        "_source": "censys",
    }
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import settings


log = logging.getLogger("openports.censys")

CENSYS_HOSTS_SEARCH = "https://search.censys.io/api/v2/hosts/search"


def _enabled() -> bool:
    if settings.CENSYS_API_ID and settings.CENSYS_API_SECRET:
        return True
    if settings.CENSYS_API_KEY:
        return True
    return False


def _auth_kwargs() -> dict[str, Any]:
    """Return the right httpx auth args for whichever credential shape is set.

    Censys supports two auth modes:
      - classic: HTTP Basic with API_ID + API_SECRET (legacy)
      - PAT: Bearer with a single CENSYS_API_KEY token (`censys_...` prefix)
    """
    if settings.CENSYS_API_ID and settings.CENSYS_API_SECRET:
        return {"auth": (settings.CENSYS_API_ID, settings.CENSYS_API_SECRET)}
    if settings.CENSYS_API_KEY:
        return {"headers": {"Authorization": f"Bearer {settings.CENSYS_API_KEY}"}}
    return {}


def _compact(hit: dict[str, Any], port: int) -> dict[str, Any]:
    autonomous_system = hit.get("autonomous_system") or {}
    location = hit.get("location") or {}
    coords = location.get("coordinates") or {}
    return {
        "ip_str": hit.get("ip"),
        "port": port,
        "org": autonomous_system.get("name"),
        "isp": autonomous_system.get("description") or autonomous_system.get("name"),
        "asn": autonomous_system.get("asn"),
        "hostnames": hit.get("dns", {}).get("reverse_dns", {}).get("names", []) if isinstance(hit.get("dns"), dict) else [],
        "domains": [],
        "transport": "tcp",
        "timestamp": hit.get("last_updated_at"),
        "product": None,
        "version": None,
        "os": hit.get("operating_system", {}).get("product") if isinstance(hit.get("operating_system"), dict) else None,
        "location": {
            "country_name": location.get("country"),
            "region_code": location.get("province"),
            "city": location.get("city"),
            "latitude": coords.get("latitude"),
            "longitude": coords.get("longitude"),
        },
        "_source": "censys",
    }


def _search(query: str, port: int, per_page: int) -> list[dict[str, Any]] | None:
    """Return candidates, or ``None`` on a hard auth/credit failure so the
    caller can stop querying the remaining ports."""
    if not _enabled():
        return []
    payload = {"q": query, "per_page": min(max(per_page, 1), 100)}
    out: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(CENSYS_HOSTS_SEARCH, params=payload, **_auth_kwargs())
            if r.status_code in (401, 402, 403):
                log.warning("censys auth/credit failure (%s): %s", r.status_code, r.text[:200])
                return None
            if r.status_code != 200:
                log.warning("censys %s -> %s: %s", query, r.status_code, r.text[:300])
                return []
            data = r.json()
            for hit in (data.get("result", {}).get("hits") or []):
                ip = hit.get("ip")
                if not ip:
                    continue
                out.append(_compact(hit, port))
    except Exception:
        log.exception("censys search failed: %s", query)
    return out


SUPPORTED_PORTS = (
    8188, 11434, 7860, 3000, 8888,
    8000, 8080, 8265, 5000, 1234, 30000, 4000, 6006, 8317,
)


def candidates_for_ports(limit: int) -> list[dict[str, Any]]:
    """Return Censys candidates for the ports we care about."""
    if not _enabled():
        return []
    out: list[dict[str, Any]] = []
    for port in SUPPORTED_PORTS:
        res = _search(f"services.port: {port}", port=port, per_page=limit)
        if res is None:
            log.warning("censys: stopping scan early (credentials rejected)")
            return out
        out.extend(res)
    return out
