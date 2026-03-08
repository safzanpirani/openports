import asyncio
import base64
import re
import httpx
import sys
import os
import warnings
from sqlmodel import Session, select
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

MAX_PAGES = 50  # Safety cap for infinite target mode
DEFAULT_PAGES = 5

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import engine
from app.models import Instance, Service
from app.fingerprints import verify_comfyui, verify_ollama
from app.config import settings
from app.telegram import send_telegram_message

SHODAN_COOKIE = settings.SHODAN_COOKIE or ""
CENSYS_API_ID = settings.CENSYS_API_ID or ""
CENSYS_API_SECRET = settings.CENSYS_API_SECRET or ""
CENSYS_API_KEY = settings.CENSYS_API_KEY or ""
ZOOMEYE_API_KEY = settings.ZOOMEYE_API_KEY or ""
CENSYS_COOKIE = settings.CENSYS_COOKIE or ""
ZOOMEYE_COOKIE = settings.ZOOMEYE_COOKIE or ""
RETRYABLE_STATUS_CODES = {403, 429, 503}
MAX_FETCH_RETRIES = 3


def _valid_ipv4s(values: set[str]) -> set[str]:
    valid_ips = set()
    for ip in values:
        parts = ip.split(".")
        if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            valid_ips.add(ip)
    return valid_ips


def _extract_ips_from_obj(obj) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for value in obj.values():
            found.update(_extract_ips_from_obj(value))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_extract_ips_from_obj(item))
    elif isinstance(obj, str):
        found.update(re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", obj))
    return _valid_ipv4s(found)


def _detect_blocked_html(text: str) -> bool:
    blocked_markers = (
        "too many requests",
        "verify you are human",
        "captcha",
        "cf-challenge",
        "cloudflare",
        "access denied",
        "please log in to use search filters",
        "please purchase a shodan membership",
    )
    lowered_html = text.lower()
    return any(marker in lowered_html for marker in blocked_markers)


def _browser_headers(cookie_value: str) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": cookie_value,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


async def scrape_shodan_page(
    query: str, page: int, client: httpx.AsyncClient
) -> tuple[set[str], bool]:
    encoded_query = quote_plus(query)
    url = f"https://www.shodan.io/search?query={encoded_query}&page={page}"
    print(f"[*] [shodan] Fetching: {url}")
    headers = _browser_headers(SHODAN_COOKIE)
    r = None
    for attempt in range(1, MAX_FETCH_RETRIES + 1):
        r = await client.get(url, headers=headers)
        if r.status_code == 200:
            break
        if r.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_FETCH_RETRIES:
            wait_seconds = attempt * 3
            print(
                f"[!] Fetch status {r.status_code} on page {page}; retrying in {wait_seconds}s (attempt {attempt}/{MAX_FETCH_RETRIES})."
            )
            await asyncio.sleep(wait_seconds)
            continue
        print(f"[-] Failed to fetch {url} (Status: {r.status_code})")
        return set(), r.status_code in RETRYABLE_STATUS_CODES

    if r is None:
        return set(), False

    ips = _valid_ipv4s(set(re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", r.text)))
    is_blocked = _detect_blocked_html(r.text)
    return ips, is_blocked


async def scrape_censys_api_page(
    query: str, page: int, client: httpx.AsyncClient
) -> tuple[set[str], bool]:
    if not CENSYS_API_KEY and not (CENSYS_API_ID and CENSYS_API_SECRET):
        return set(), False

    url = "https://search.censys.io/api/v2/hosts/search"
    if CENSYS_API_KEY:
        headers = {
            "Authorization": f"Bearer {CENSYS_API_KEY}",
            "Accept": "application/json",
        }
    else:
        auth = base64.b64encode(
            f"{CENSYS_API_ID}:{CENSYS_API_SECRET}".encode("utf-8")
        ).decode("ascii")
        headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    params = {"q": query, "per_page": 100, "page": page}
    print(f"[*] [censys] Fetching: {url} page={page}")
    r = await client.get(url, headers=headers, params=params)
    if r.status_code != 200:
        print(f"[-] [censys] Failed page {page} (Status: {r.status_code})")
        return set(), r.status_code in RETRYABLE_STATUS_CODES or r.status_code in {
            401,
            402,
        }

    payload = r.json()
    hits = payload.get("result", {}).get("hits", [])
    ips = _extract_ips_from_obj(hits)
    return ips, False


async def scrape_zoomeye_api_page(
    query: str, page: int, client: httpx.AsyncClient
) -> tuple[set[str], bool]:
    if not ZOOMEYE_API_KEY:
        return set(), False
    url = "https://api.zoomeye.ai/host/search"
    headers = {
        "API-KEY": ZOOMEYE_API_KEY,
        "Authorization": f"JWT {ZOOMEYE_API_KEY}",
        "Accept": "application/json",
    }
    params = {"query": query, "page": page}
    print(f"[*] [zoomeye] Fetching: {url} page={page}")
    r = await client.get(url, headers=headers, params=params)
    if r.status_code != 200:
        print(f"[-] [zoomeye] Failed page {page} (Status: {r.status_code})")
        return set(), r.status_code in RETRYABLE_STATUS_CODES or r.status_code in {
            401,
            402,
        }
    payload = r.json()
    ips = _extract_ips_from_obj(payload.get("matches", []))
    if not ips:
        ips = _extract_ips_from_obj(payload)
    return ips, False


async def scrape_censys_web_page(
    query: str, page: int, client: httpx.AsyncClient
) -> tuple[set[str], bool]:
    if not CENSYS_COOKIE:
        return set(), False
    encoded_query = quote_plus(query)
    url = (
        f"https://search.censys.io/search?resource=hosts&q={encoded_query}&page={page}"
    )
    print(f"[*] [censys-web] Fetching: {url}")
    r = await client.get(url, headers=_browser_headers(CENSYS_COOKIE))
    if r.status_code != 200:
        print(f"[-] [censys-web] Failed page {page} (Status: {r.status_code})")
        return set(), r.status_code in RETRYABLE_STATUS_CODES or r.status_code in {
            401,
            402,
            403,
        }
    ips = _valid_ipv4s(set(re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", r.text)))
    return ips, _detect_blocked_html(r.text)


async def scrape_zoomeye_web_page(
    query: str, page: int, client: httpx.AsyncClient
) -> tuple[set[str], bool]:
    if not ZOOMEYE_COOKIE:
        return set(), False
    encoded_query = quote_plus(query)
    candidates = [
        f"https://www.zoomeye.ai/searchResult?q={encoded_query}&page={page}",
        f"https://www.zoomeye.ai/search?q={encoded_query}&page={page}",
    ]
    last_blocked = False
    for url in candidates:
        print(f"[*] [zoomeye-web] Fetching: {url}")
        r = await client.get(url, headers=_browser_headers(ZOOMEYE_COOKIE))
        if r.status_code != 200:
            continue
        ips = _valid_ipv4s(
            set(re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", r.text))
        )
        blocked = _detect_blocked_html(r.text)
        if ips or blocked:
            return ips, blocked
        last_blocked = blocked
    return set(), last_blocked


async def scrape_censys_page(
    query: str, page: int, client: httpx.AsyncClient
) -> tuple[set[str], bool]:
    if CENSYS_COOKIE:
        return await scrape_censys_web_page(query, page, client)
    return await scrape_censys_api_page(query, page, client)


async def scrape_zoomeye_page(
    query: str, page: int, client: httpx.AsyncClient
) -> tuple[set[str], bool]:
    if ZOOMEYE_COOKIE:
        return await scrape_zoomeye_web_page(query, page, client)
    return await scrape_zoomeye_api_page(query, page, client)


async def check_ip(
    ip: str, port: int, service: Service, client: httpx.AsyncClient
) -> dict | None:
    base_url = f"http://{ip}:{port}"
    if service == Service.comfyui:
        ok, meta, models, version, gpu_name, metrics = await verify_comfyui(
            base_url, client
        )
    else:
        ok, meta, models, version, metrics = await verify_ollama(base_url, client)
        gpu_name = None

    if not ok:
        return None

    return {
        "ip": ip,
        "port": port,
        "service": service,
        "version": version,
        "gpu_name": gpu_name,
        "metrics": metrics,
        "models": models,
    }


async def process_ips(
    ips: set[str],
    port: int,
    service: Service,
    force_rescan: bool = False,
    target_gpu: str | None = None,
    target_model: str | None = None,
) -> bool:
    with Session(engine) as s:
        if not force_rescan:
            # Check tracking to avoid repeats in 24h
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            # Remove objects that don't have timezone by replacing with .replace(tzinfo=None) or keep them naive
            # Actually, SQLModel models probably use naive datetimes if default is naive. Let's stick to datetime.utcnow() but suppress warning or use UTC without warning.
            cutoff = cutoff.replace(tzinfo=None)
            stmt = (
                select(Instance.ip)
                .where(Instance.port == port)
                .where(Instance.last_checked_at > cutoff)
            )
            recent_ips = set(s.exec(stmt).all())
        else:
            recent_ips = set()

        new_ips = ips - recent_ips
        print(
            f"[*] Found {len(ips)} IPs, but {len(recent_ips)} were already checked recently. Scanning {len(new_ips)} fresh IPs..."
        )

        if not new_ips:
            return False

        limits = httpx.Limits(max_connections=20)
        timeout = httpx.Timeout(5.0)

        results = []
        async with httpx.AsyncClient(
            limits=limits, timeout=timeout, follow_redirects=True
        ) as client:
            tasks = [check_ip(ip, port, service, client) for ip in new_ips]
            completed = await asyncio.gather(*tasks, return_exceptions=True)

            for ip, res in zip(new_ips, completed):
                # Update DB (just bumping last_checked_at for failed so we don't repeat them)
                stmt_inst = select(Instance).where(
                    Instance.ip == ip, Instance.port == port
                )
                inst = s.exec(stmt_inst).first()
                if not inst:
                    inst = Instance(ip=ip, port=port, service=service)
                inst.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)

                if isinstance(res, Exception) or not res:
                    inst.is_alive = False
                    inst.last_error = (
                        str(res)
                        if isinstance(res, Exception)
                        else "Verification failed"
                    )
                else:
                    inst.is_alive = True
                    inst.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    inst.version = res["version"]
                    inst.gpu_name = res["gpu_name"]
                    metrics = res["metrics"]
                    for f in (
                        "model_count",
                        "vram_total_gb",
                        "vram_free_gb",
                        "ram_total_gb",
                        "ram_free_gb",
                        "max_model_params",
                        "max_context",
                        "node_count",
                    ):
                        val = metrics.get(f)
                        if val is not None:
                            setattr(inst, f, val)
                    results.append(res)

                s.add(inst)
            s.commit()

        print(f"[*] Successfully verified {len(results)} out of {len(new_ips)} IPs.")

        found_target = False
        # Build Summary Report for Telegram
        if results:
            msg = ""
            nodes_to_report = []

            for r in results:
                models_dict = r.get("models")
                exact_models = []
                if isinstance(models_dict, dict):
                    if service == Service.comfyui:
                        for folder, items in models_dict.items():
                            if folder != "types" and isinstance(items, list):
                                exact_models.extend(
                                    [str(m) for m in items if isinstance(m, str)]
                                )
                    elif service == Service.ollama:
                        tags = models_dict.get("tags")
                        if isinstance(tags, dict):
                            items = tags.get("models")
                            if isinstance(items, list):
                                exact_models.extend(
                                    [
                                        m.get("name")
                                        for m in items
                                        if isinstance(m, dict) and "name" in m
                                    ]
                                )

                is_match_gpu = False
                is_match_model = False
                if (
                    target_gpu is not None
                    and r.get("gpu_name")
                    and target_gpu.lower() in r["gpu_name"].lower()
                ):
                    is_match_gpu = True

                if target_model is not None and any(
                    target_model.lower() in m.lower() for m in exact_models
                ):
                    is_match_model = True

                if target_gpu or target_model:
                    if (target_gpu and is_match_gpu) or (
                        target_model and is_match_model
                    ):
                        found_target = True
                        nodes_to_report.append((r, exact_models))
                else:
                    nodes_to_report.append((r, exact_models))

            if nodes_to_report:
                if target_gpu or target_model:
                    msg += f"🎯 FOUND {service.value.upper()} MATCHING TARGET!\n\n"
                else:
                    msg = f"🔍 Scraped {len(ips)} IPs -> Verified {len(results)} {service.value.upper()} nodes\n\n"

                for r, exact_models in nodes_to_report:
                    msg += f"🖥 `{r['ip']}:{r['port']}`\n"
                    if r["version"]:
                        msg += f"v{r['version']} | "
                    if r["gpu_name"]:
                        msg += f"GPU: {r['gpu_name']} | "
                    mets = r.get("metrics", {})
                    if mets.get("model_count"):
                        msg += f"Models: {mets['model_count']} | "
                    if mets.get("max_model_params"):
                        msg += f"Max Params: {mets['max_model_params']}B | "
                    if mets.get("vram_free_gb") is not None:
                        msg += f"VRAM Free: {mets['vram_free_gb']:.1f}GB"

                    if exact_models:
                        max_disp = 10
                        displayed = ", ".join(exact_models[:max_disp])
                        if len(exact_models) > max_disp:
                            displayed += f" (+{len(exact_models) - max_disp} more)"
                        msg += f"\n📦 {displayed}"

                    msg += "\n\n"

                # Telegram has a 4096 character limit
                if len(msg) > 4000:
                    msg = msg[:4000] + "\n... [Message Truncated] ..."
                await send_telegram_message(msg.strip())

        return found_target


async def main():
    force_rescan = "--force" in sys.argv
    max_pages_override = next(
        (
            int(sys.argv[i + 1])
            for i, arg in enumerate(sys.argv)
            if arg == "--max-pages"
            and i + 1 < len(sys.argv)
            and sys.argv[i + 1].isdigit()
            and int(sys.argv[i + 1]) > 0
        ),
        None,
    )
    target_gpu = next(
        (
            sys.argv[i + 1]
            for i, arg in enumerate(sys.argv)
            if arg == "--target-gpu" and i + 1 < len(sys.argv)
        ),
        None,
    )
    target_model = next(
        (
            sys.argv[i + 1]
            for i, arg in enumerate(sys.argv)
            if arg == "--target-model" and i + 1 < len(sys.argv)
        ),
        None,
    )

    queries = [
        {
            "service": Service.comfyui,
            "port": 8188,
            "shodan": 'port:8188 html:"ComfyUI"',
            "censys": "services.port: 8188",
            "zoomeye": 'port="8188" && app="ComfyUI"',
        },
        {
            "service": Service.ollama,
            "port": 11434,
            "shodan": 'port:11434 html:"Ollama"',
            "censys": "services.port: 11434",
            "zoomeye": 'port="11434" && app="Ollama"',
        },
    ]

    providers = [
        ("shodan", True, scrape_shodan_page),
        (
            "censys",
            bool(
                CENSYS_COOKIE or CENSYS_API_KEY or (CENSYS_API_ID and CENSYS_API_SECRET)
            ),
            scrape_censys_page,
        ),
        ("zoomeye", bool(ZOOMEYE_COOKIE or ZOOMEYE_API_KEY), scrape_zoomeye_page),
    ]

    page_limit = max_pages_override or DEFAULT_PAGES

    async with httpx.AsyncClient() as client:
        for cfg in queries:
            service = cfg["service"]
            port = cfg["port"]
            print(f"=== Starting scan for {service.value} ===")
            for provider_name, provider_enabled, provider_fetcher in providers:
                if not provider_enabled:
                    print(f"[-] [{provider_name}] Not configured; skipping.")
                    continue

                print(
                    f"--- Provider {provider_name} ({service.value}) page window 1-{page_limit} ---"
                )
                blocked_hits = 0
                warned_block = False
                found_target_for_provider = False

                for page in range(1, page_limit + 1):
                    query = cfg[provider_name]
                    ips, is_blocked = await provider_fetcher(query, page, client)

                    if is_blocked:
                        blocked_hits += 1
                        if provider_name == "shodan" and not warned_block:
                            warned_block = True
                            await send_telegram_message(
                                f"⚠️ Shodan may be rate-limiting/anti-bot blocking the scraper for {service.value} (page {page})."
                            )
                    else:
                        blocked_hits = 0

                    if blocked_hits >= 3:
                        print(
                            f"[!] [{provider_name}] Repeated blocked responses for {service.value}; stopping this provider."
                        )
                        break

                    if not ips:
                        if page < page_limit:
                            print(
                                f"[-] [{provider_name}] No IPs found on page {page}, continuing until page {page_limit}."
                            )
                            await asyncio.sleep(2)
                            continue
                        print(
                            f"[-] [{provider_name}] No IPs found on page {page}, stopping {service.value} provider scan."
                        )
                        break

                    found_target = await process_ips(
                        ips, port, service, force_rescan, target_gpu, target_model
                    )
                    if found_target:
                        found_target_for_provider = True
                        print(
                            f"[+] [{provider_name}] Found target for {service.value}; stopping this provider early."
                        )
                        break

                    await asyncio.sleep(2)

                if found_target_for_provider and (target_gpu or target_model):
                    break


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.run(main())
