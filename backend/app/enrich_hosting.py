# -*- coding: utf-8 -*-
"""Classify hosting/provider type for an IP using DNS, ASN heuristics, and Shodan metadata.

Uses only non-intrusive, publicly available lookups (reverse DNS, ASN → provider mapping).
No external API calls required.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Known ASNs for major cloud / VPS providers
# ---------------------------------------------------------------------------
KNOWN_CLOUD_ASNS: dict[str, str] = {
    # AWS
    "AS16509": "aws",
    "AS14618": "aws",
    "AS38895": "aws",
    "AS39111": "aws",
    "AS45102": "aws",  # AWS Global Accelerator
    # GCP
    "AS396982": "gcp",
    "AS15169": "gcp",
    "AS139070": "gcp",
    "AS26910": "gcp",  # reserved, sometimes appears
    # Azure
    "AS8075": "azure",
    "AS8070": "azure",
    "AS12076": "azure",
    "AS6584": "azure",
    "AS45125": "azure",
    # DigitalOcean
    "AS14061": "digitalocean",
    "AS393406": "digitalocean",  # private?
    # Vultr
    "AS20473": "vultr",
    "AS64515": "vultr",
    "AS396190": "vultr",
    # Linode/Akamai
    "AS63949": "linode",
    "AS20940": "linode",  # Akamai / Linode
    # Hetzner
    "AS24940": "hetzner",
    "AS213230": "hetzner",
    # OVH
    "AS16276": "ovh",
    "AS35540": "ovh",
    # Oracle Cloud
    "AS31898": "oracle_cloud",
    "AS7920": "oracle_cloud",
    # Alibaba Cloud
    "AS45102": "alibaba_cloud",
    "AS37963": "alibaba_cloud",
    # Tencent Cloud
    "AS132203": "tencent_cloud",
    "AS45090": "tencent_cloud",
    # Huawei Cloud
    "AS55990": "huawei_cloud",
    # Scaleway
    "AS12876": "scaleway",
    "AS29447": "scaleway",
    # Upcloud
    "AS202053": "upcloud",
    # IONOS / 1&1
    "AS8560": "ionos",
    # LeaseWeb
    "AS16265": "leaseweb",
    "AS60781": "leaseweb",
    # Psychz
    "AS40676": "psychz",
    # BuyVM / FranTech
    "AS53667": "buyvm",
    # HostHatch
    "AS63473": "hosthatch",
    # RamNode
    "AS3842": "ramnode",
    # Contabo
    "AS51167": "contabo",
    # DediPath
    "AS35913": "dedipath",
    # Equinix Metal (ex Packet)
    "AS54825": "equinix_metal",
    # IBM Cloud / SoftLayer
    "AS36351": "ibm_cloud",
    # Rackspace
    "AS33070": "rackspace",
    # GoDaddy
    "AS26496": "godaddy",
    # OVH US
    "AS7018": "ovh",
    # Choopa / ReliableSite (sometimes used for rented servers)
    "AS20473": "choopa",
    # Clouvider
    "AS62240": "clouvider",
    # MegaZone (Evoxt)
    "AS9312": "evoxt",
    # Xerhost
    "AS207046": "xerhost",
    # Tarhely.eu
    "AS43359": "tarhely",
    # First Colo (often rented servers; some are consumer)
    "AS24961": "firstcolo",
    # Datalix
    "AS200195": "datalix",
    # Ipxo
    "AS204564": "ipxo",
    # Iomart
    "AS20860": "iomart",
    # UK2.net
    "AS13213": "uk2",
    # OVHcloud
    "AS41313": "ovh",
    # Verasel
    "AS395111": "verasel",
    # HIVELOCITY
    "AS29802": "hivelocity",
    # QuadraNet
    "AS8100": "quadranet",
    # Joe's Datacenter
    "AS19969": "joes_datacenter",
    # AllGenTech
    "AS401297": "allgentech",
    # SpeedyPage
    "AS393514": "speedypage",
    # Nexril
    "AS397789": "nexril",
    # MivoCloud
    "AS39798": "mivocloud",
}

# ---------------------------------------------------------------------------
# Reverse DNS patterns
# ---------------------------------------------------------------------------
KNOWN_CLOUD_PTR_PATTERNS: list[tuple[str | re.Pattern, str]] = [
    (re.compile(r"\.compute\.amazonaws\.com$", re.I), "aws"),
    (re.compile(r"\.compute-1\.amazonaws\.com$", re.I), "aws"),
    (re.compile(r"\.amazonaws\.com$", re.I), "aws"),
    (re.compile(r"bc\.googleusercontent\.com$", re.I), "gcp"),
    (re.compile(r"\.googlevpc\.com$", re.I), "gcp"),
    (re.compile(r"cloudapp\.azure\.com$", re.I), "azure"),
    (re.compile(r"cloudapp\.net$", re.I), "azure"),
    (re.compile(r"\.digitalocean\.com$", re.I), "digitalocean"),
    (re.compile(r"\.vultrusercontent\.com$", re.I), "vultr"),
    (re.compile(r"\.vultr\.com$", re.I), "vultr"),
    (re.compile(r"your-server\.de$", re.I), "hetzner"),
    (re.compile(r"\.your-server\.de$", re.I), "hetzner"),
    (re.compile(r"\.hetzner\.de$", re.I), "hetzner"),
    ("linodeusercontent.com", "linode"),
    ("members.linode.com", "linode"),
    (re.compile(r"\.ovh\.net$", re.I), "ovh"),
    (re.compile(r"\.scw\.cloud$", re.I), "scaleway"),
    (re.compile(r"\.scaleway\.com$", re.I), "scaleway"),
    (re.compile(r"\.upcloud\.host$", re.I), "upcloud"),
    (re.compile(r"\.oraclecloud\.com$", re.I), "oracle_cloud"),
    (re.compile(r"\.alibabacloud\.com$", re.I), "alibaba_cloud"),
    (re.compile(r"\.tencent\.com$", re.I), "tencent_cloud"),
    (re.compile(r"\.myhuaweicloud\.com$", re.I), "huawei_cloud"),
    (re.compile(r"\.leaseweb\.com$", re.I), "leaseweb"),
    (re.compile(r"\.leaseweb\.net$", re.I), "leaseweb"),
    (re.compile(r"\.contabo\.com$", re.I), "contabo"),
    (re.compile(r"\.contaboserver\.net$", re.I), "contabo"),
    (re.compile(r"\.dedipath\.com$", re.I), "dedipath"),
    (re.compile(r"\.frantech\.ca$", re.I), "buyvm"),
    (re.compile(r"\.buyvm\.net$", re.I), "buyvm"),
    (re.compile(r"\.hosthatch\.com$", re.I), "hosthatch"),
    (re.compile(r"\.equinix\.com$", re.I), "equinix_metal"),
    (re.compile(r"\.packet\.net$", re.I), "equinix_metal"),
    (re.compile(r"\.softlayer\.com$", re.I), "ibm_cloud"),
    (re.compile(r"\.rackspace\.com$", re.I), "rackspace"),
    (re.compile(r"\.secureserver\.net$", re.I), "godaddy"),
    (re.compile(r"\.psychz\.net$", re.I), "psychz"),
    (re.compile(r"\.vertex-host\.com$", re.I), "vertex_host"),
    (re.compile(r"\.mivocloud\.com$", re.I), "mivocloud"),
    ("clouvider.net", "clouvider"),
    (re.compile(r"\.ipxcore\.com$", re.I), "ipxcore"),
    (re.compile(r"\.hivelocity\.net$", re.I), "hivelocity"),
    (re.compile(r"\.quadranet\.com$", re.I), "quadranet"),
]

# ---------------------------------------------------------------------------
# ISP / org heuristics from Shodan compact
# ---------------------------------------------------------------------------
SHODAN_ORG_CLOUD_HINTS: dict[str, str] = {
    "amazon.com": "aws",
    "amazon technologies": "aws",
    "google llc": "gcp",
    "google cloud": "gcp",
    "microsoft corporation": "azure",
    "microsoft azure": "azure",
    "digitalocean, llc": "digitalocean",
    "digitalocean": "digitalocean",
    "the constant company, llc": "vultr",
    "choopa, llc": "vultr",
    "hetzner online gmbh": "hetzner",
    "linode, llc": "linode",
    "akamai connected cloud": "linode",
    "ovh": "ovh",
    "ovh hosting": "ovh",
    "ovh sas": "ovh",
    "oracle corporation": "oracle_cloud",
    "alibaba": "alibaba_cloud",
    "alibaba cloud": "alibaba_cloud",
    "tencent cloud computing": "tencent_cloud",
    "tencent": "tencent_cloud",
    "huawei cloud": "huawei_cloud",
    "scaleway": "scaleway",
    "online sas": "scaleway",
    "upcloud": "upcloud",
    "ionos": "ionos",
    "1&1": "ionos",
    "leaseweb": "leaseweb",
    "psychz networks": "psychz",
    "fran tech solutions": "buyvm",
    "hosthatch": "hosthatch",
    "contabo": "contabo",
    "dedipath": "dedipath",
    "equinix": "equinix_metal",
    "ibm": "ibm_cloud",
    "softlayer": "ibm_cloud",
    "rackspace": "rackspace",
    "godaddy": "godaddy",
    "24 shells": "buyvm",
    "hivelocity": "hivelocity",
    "quadranet": "quadranet",
    "clouvider": "clouvider",
    "mivocloud": "mivocloud",
}

# ISP names that are definitely residential / consumer ISPs (not VPS)
RESIDENTIAL_ISP_HINTS: set[str] = {
    "comcast cable",
    "comcast",
    "charter communications",
    "spectrum",
    "at&t",
    "verizon",
    "verizon fios",
    "fios",
    "centurylink",
    "cox communications",
    "frontier communications",
    "altice",
    "bt",
    "bt group",
    "sky uk",
    "talktalk",
    "virgin media",
    "vodafone",
    "deutsche telekom",
    "telefonica",
    "orange",
    "t-mobile",
    "kddi",
    "ntt",
    "softbank",
    "china telecom",
    "china unicom",
    "china mobile",
    "rogers",
    "bell canada",
    "telus",
    "optus",
    "telstra",
    "vodafone",
    "cox",
}

# PTR substrings that definitely indicate residential connections
RESIDENTIAL_PTR_HINTS: list[str] = [
    ".fios.",
    ".verizon.net",
    ".verizon.com",
    ".mycingular.net",
    ".res.rr.com",
    ".res.rr.",
    ".hsd1.",
    ".hsd2.",
    ".dyn.",
    ".dynamic.",
    ".pool.",
    ".customer.",
    ".users.",
    ".client.",
    ".dhcp.",
    ".home.",
    ".cpe.",
    ".cable.",
]


async def _reverse_dns(ip: str, timeout: float = 3.0) -> str | None:
    """Best-effort reverse DNS lookup (non-blocking, thread-pool'd)."""

    import socket

    def _resolve():
        try:
            return socket.gethostbyaddr(ip)[0]
        except (socket.herror, socket.gaierror, OSError):
            return None

    try:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, _resolve),
            timeout=timeout,
        )
    except (asyncio.TimeoutError, Exception):
        return None


def _classify_from_ptr(ptr: str | None) -> str | None:
    """Return provider name from reverse DNS patterns, or None."""

    if not ptr:
        return None

    ptr_lower = ptr.lower()
    for pattern, name in KNOWN_CLOUD_PTR_PATTERNS:
        if isinstance(pattern, str):
            if pattern in ptr_lower:
                return name
        elif isinstance(pattern, re.Pattern):
            if pattern.search(ptr_lower):
                return name

    return None


def _classify_from_asn(asn: str | None) -> str | None:
    """Return provider from known cloud ASN map."""

    if not asn:
        return None
    # strip optional "AS" prefix and leading zeros
    asn_clean = asn.strip().upper().removeprefix("AS")
    return KNOWN_CLOUD_ASNS.get(f"AS{asn_clean}")


def _classify_from_shodan_org(org: str | None, isp: str | None) -> str | None:
    """Heuristic classification from Shodan org/isp fields."""

    for candidate in (org, isp):
        if not candidate:
            continue
        c = candidate.lower().strip()
        for hint, provider in SHODAN_ORG_CLOUD_HINTS.items():
            if hint in c:
                return provider

    return None


def _is_residential_ptr(ptr: str | None) -> bool:
    """Check whether the reverse DNS suggests a residential connection."""

    if not ptr:
        return False
    p = ptr.lower()
    return any(hint in p for hint in RESIDENTIAL_PTR_HINTS)


def _is_residential_isp(isp: str | None) -> bool:
    """Check whether the ISP is a known consumer/residential provider."""

    if not isp:
        return False
    c = isp.lower().strip()
    return any(hint in c for hint in RESIDENTIAL_ISP_HINTS)


def classify_provider(
    asn: str | None = None,
    reverse_dns: str | None = None,
    shodan_org: str | None = None,
    shodan_isp: str | None = None,
) -> str:
    """Return the best-guess provider category for an IP.

    Priority:
    1) reverse DNS match (most accurate)
    2) ASN match
    3) Shodan org/isp heuristic
    4) residential ISP detection
    5) fallback "unknown"
    """

    # 1) reverse DNS
    provider = _classify_from_ptr(reverse_dns)
    if provider:
        return provider

    # 2) ASN
    provider = _classify_from_asn(asn)
    if provider:
        return provider

    # 3) Shodan org/isp
    provider = _classify_from_shodan_org(shodan_org, shodan_isp)
    if provider:
        return provider

    # 4) residential ISP check
    if _is_residential_isp(shodan_isp):
        return "residential"

    # 5) residential PTR hints
    if _is_residential_ptr(reverse_dns):
        return "residential"

    return "unknown"


async def enrich_ip_hosting(ip: str) -> dict[str, str | None]:
    """Return hosting enrichment for a single IP."""

    ptr = await _reverse_dns(ip)
    provider = classify_provider(
        reverse_dns=ptr,
    )

    return {
        "reverse_dns": ptr,
        "provider": provider,
    }
