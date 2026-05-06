"""ZoomEye candidate fetcher.

Uses ZOOMEYE_API_KEY against the public host search endpoint. Returns
candidates in the same compact shape as Shodan/Censys.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import settings


log = logging.getLogger("openports.zoomeye")

ZOOMEYE_HOST_SEARCH = "https://api.zoomeye.ai/host/search"


def _enabled() -> bool:
    return bool(settings.ZOOMEYE_API_KEY)


def _compact(rec: dict[str, Any], port: int) -> dict[str, Any]:
    geo = rec.get("geoinfo") or {}
    asn_obj = geo.get("asn") or {}
    return {
        "ip_str": rec.get("ip"),
        "port": port,
        "org": (rec.get("portinfo") or {}).get("organization") or geo.get("organization"),
        "isp": geo.get("isp"),
        "asn": asn_obj.get("number") if isinstance(asn_obj, dict) else asn_obj,
        "hostnames": rec.get("rdns_new") and [rec["rdns_new"]] or [],
        "domains": [],
        "transport": "tcp",
        "timestamp": rec.get("timestamp"),
        "product": (rec.get("portinfo") or {}).get("product"),
        "version": (rec.get("portinfo") or {}).get("version"),
        "os": (rec.get("portinfo") or {}).get("os"),
        "location": {
            "country_name": (geo.get("country") or {}).get("names", {}).get("en")
            if isinstance(geo.get("country"), dict) else geo.get("country"),
            "region_code": (geo.get("subdivisions") or {}).get("names", {}).get("en")
            if isinstance(geo.get("subdivisions"), dict) else None,
            "city": (geo.get("city") or {}).get("names", {}).get("en")
            if isinstance(geo.get("city"), dict) else geo.get("city"),
            "latitude": (geo.get("location") or {}).get("lat") if isinstance(geo.get("location"), dict) else None,
            "longitude": (geo.get("location") or {}).get("lon") if isinstance(geo.get("location"), dict) else None,
        },
        "_source": "zoomeye",
    }


def _search(query: str, port: int, page: int = 1) -> list[dict[str, Any]]:
    if not _enabled():
        return []
    headers = {"API-KEY": settings.ZOOMEYE_API_KEY or ""}
    params = {"query": query, "page": page}
    out: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(ZOOMEYE_HOST_SEARCH, params=params, headers=headers)
            if r.status_code != 200:
                log.warning("zoomeye %s -> %s: %s", query, r.status_code, r.text[:300])
                return []
            data = r.json()
            for rec in (data.get("matches") or []):
                ip = rec.get("ip")
                if not ip:
                    continue
                out.append(_compact(rec, port))
    except Exception:
        log.exception("zoomeye search failed: %s", query)
    return out


def candidates_for_ports(limit: int) -> list[dict[str, Any]]:
    if not _enabled():
        return []
    # ZoomEye paginates with ~20 per page; pull a couple of pages if needed.
    pages = max(1, min(5, (limit + 19) // 20))
    out: list[dict[str, Any]] = []
    for port in (8188, 11434):
        for p in range(1, pages + 1):
            out.extend(_search(f"port:{port}", port=port, page=p))
    return out
