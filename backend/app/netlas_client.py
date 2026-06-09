"""Netlas candidate fetcher.

Free tier is ~50 requests/day per key, so `NETLAS_API_KEY` accepts a
comma-separated list of keys and we round-robin between them. On 401/403/429
from one key, we transparently fail over to the next so a key getting
rate-limited mid-scan doesn't sink the whole run.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import settings


log = logging.getLogger("openports.netlas")

NETLAS_RESPONSES = "https://app.netlas.io/api/responses/"


def _keys() -> list[str]:
    raw = settings.NETLAS_API_KEY or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _enabled() -> bool:
    return bool(_keys())


_rr_idx = 0


def _next_key() -> str:
    global _rr_idx
    keys = _keys()
    if not keys:
        return ""
    k = keys[_rr_idx % len(keys)]
    _rr_idx += 1
    return k


def _coerce_asn(v: Any) -> int | None:
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.upper().lstrip("AS").strip()
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _compact(item: dict[str, Any], port: int) -> dict[str, Any]:
    data = item.get("data") if isinstance(item.get("data"), dict) else item
    geo = data.get("geo") or {}
    whois = data.get("whois") or {}
    asn_obj = whois.get("asn") if isinstance(whois.get("asn"), dict) else {}
    net_obj = whois.get("net") if isinstance(whois.get("net"), dict) else {}
    http = data.get("http") if isinstance(data.get("http"), dict) else {}

    loc = geo.get("location") if isinstance(geo.get("location"), dict) else {}

    return {
        "ip_str": data.get("ip"),
        "port": data.get("port") or port,
        "org": net_obj.get("organization") or asn_obj.get("name"),
        "isp": asn_obj.get("name"),
        "asn": _coerce_asn(asn_obj.get("asn") or asn_obj.get("number")),
        "hostnames": [data["rdns"]] if data.get("rdns") else [],
        "domains": [data["domain"]] if data.get("domain") else [],
        "transport": data.get("protocol") or "tcp",
        "timestamp": data.get("last_updated") or data.get("@timestamp"),
        "product": http.get("server") or http.get("title"),
        "version": None,
        "os": None,
        "location": {
            "country_name": geo.get("country"),
            "region_code": geo.get("province") or geo.get("region"),
            "city": geo.get("city"),
            "latitude": loc.get("lat"),
            "longitude": loc.get("lon"),
        },
        "_source": "netlas",
    }


def _search(query: str, port: int, size: int = 20) -> list[dict[str, Any]]:
    """Run one Netlas search, rotating keys on quota errors."""
    if not _enabled():
        return []
    keys = _keys()
    last_err: str | None = None
    for _ in range(len(keys)):
        key = _next_key()
        headers = {"X-API-Key": key, "Accept": "application/json"}
        params = {"q": query, "size": min(max(size, 1), 20)}
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.get(NETLAS_RESPONSES, params=params, headers=headers)
            if r.status_code in (401, 403, 429):
                last_err = f"{r.status_code}: {r.text[:200]}"
                log.warning(
                    "netlas key …%s -> %s, rotating",
                    key[-6:] if len(key) >= 6 else key,
                    r.status_code,
                )
                continue
            if r.status_code != 200:
                log.warning("netlas %s -> %s: %s", query, r.status_code, r.text[:300])
                return []
            data = r.json()
            out: list[dict[str, Any]] = []
            for item in (data.get("items") or []):
                d = item.get("data") if isinstance(item.get("data"), dict) else item
                if not (d and d.get("ip")):
                    continue
                out.append(_compact(item, port))
            return out
        except Exception:
            log.exception("netlas search failed: %s", query)
            return []
    if last_err:
        log.warning("all netlas keys exhausted for %s: %s", query, last_err)
    return []


# Same port set as the other source clients — _service_from_port maps these.
SUPPORTED_PORTS = (
    8188, 11434, 7860, 3000, 8888,
    8000, 8080, 8265, 5000, 1234, 30000, 4000, 6006, 8317,
)


def candidates_for_ports(limit: int) -> list[dict[str, Any]]:
    if not _enabled():
        return []
    # Netlas free tier: ~50 req/key/day. One request per port keeps it cheap.
    # `size` caps results per call; bump up to 20 (Netlas free-plan max).
    size = min(max(limit // max(len(SUPPORTED_PORTS), 1), 1), 20)
    out: list[dict[str, Any]] = []
    for port in SUPPORTED_PORTS:
        out.extend(_search(f"port:{port}", port=port, size=size))
    return out
