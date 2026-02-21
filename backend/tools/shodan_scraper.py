import asyncio
import re
import httpx
import sys
import os
import warnings
from sqlmodel import Session, select
from datetime import datetime, timedelta, timezone

MAX_PAGES = 50  # Safety cap for infinite target mode

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import engine
from app.models import Instance, Service
from app.fingerprints import verify_comfyui, verify_ollama
from app.config import settings
from app.telegram import send_telegram_message

SHODAN_COOKIE = settings.SHODAN_COOKIE or ""

async def scrape_shodan_page(query: str, page: int, client: httpx.AsyncClient) -> set[str]:
    url = f"https://www.shodan.io/search?query={query}&page={page}"
    print(f"[*] Fetching: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": SHODAN_COOKIE
    }
    r = await client.get(url, headers=headers)
    if r.status_code != 200:
        print(f"[-] Failed to fetch {url} (Status: {r.status_code})")
        return set()
    
    ips = set(re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", r.text))
    # Filter out valid IPs
    valid_ips = set()
    for ip in ips:
        parts = ip.split(".")
        if len(parts) == 4 and all(0 <= int(p) <= 255 for p in parts):
            valid_ips.add(ip)
    
    return valid_ips

async def check_ip(ip: str, port: int, service: Service, client: httpx.AsyncClient) -> dict | None:
    base_url = f"http://{ip}:{port}"
    if service == Service.comfyui:
        ok, meta, models, version, gpu_name, metrics = await verify_comfyui(base_url, client)
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
        "models": models
    }

async def process_ips(ips: set[str], port: int, service: Service, force_rescan: bool = False, target_gpu: str | None = None, target_model: str | None = None) -> bool:
    with Session(engine) as s:
        if not force_rescan:
            # Check tracking to avoid repeats in 24h
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            # Remove objects that don't have timezone by replacing with .replace(tzinfo=None) or keep them naive 
            # Actually, SQLModel models probably use naive datetimes if default is naive. Let's stick to datetime.utcnow() but suppress warning or use UTC without warning.
            cutoff = cutoff.replace(tzinfo=None)
            stmt = select(Instance.ip).where(Instance.port == port).where(Instance.last_checked_at > cutoff)
            recent_ips = set(s.exec(stmt).all())
        else:
            recent_ips = set()
        
        new_ips = ips - recent_ips
        print(f"[*] Found {len(ips)} IPs, but {len(recent_ips)} were already checked recently. Scanning {len(new_ips)} fresh IPs...")
        
        if not new_ips:
            return False

        limits = httpx.Limits(max_connections=20)
        timeout = httpx.Timeout(5.0)
        
        results = []
        async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True) as client:
            tasks = [check_ip(ip, port, service, client) for ip in new_ips]
            completed = await asyncio.gather(*tasks, return_exceptions=True)
            
            for ip, res in zip(new_ips, completed):
                # Update DB (just bumping last_checked_at for failed so we don't repeat them)
                stmt_inst = select(Instance).where(Instance.ip == ip, Instance.port == port)
                inst = s.exec(stmt_inst).first()
                if not inst:
                    inst = Instance(ip=ip, port=port, service=service)
                inst.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
                
                if isinstance(res, Exception) or not res:
                    inst.is_alive = False
                    inst.last_error = str(res) if isinstance(res, Exception) else "Verification failed"
                else:
                    inst.is_alive = True
                    inst.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    inst.version = res["version"]
                    inst.gpu_name = res["gpu_name"]
                    metrics = res["metrics"]
                    for f in ("model_count", "vram_total_gb", "vram_free_gb", "ram_total_gb", "ram_free_gb", "max_model_params", "max_context", "node_count"):
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
                                exact_models.extend([str(m) for m in items if isinstance(m, str)])
                    elif service == Service.ollama:
                        tags = models_dict.get("tags")
                        if isinstance(tags, dict):
                            items = tags.get("models")
                            if isinstance(items, list):
                                exact_models.extend([m.get("name") for m in items if isinstance(m, dict) and "name" in m])
                
                is_match_gpu = False
                is_match_model = False
                if target_gpu is not None and r.get("gpu_name") and target_gpu.lower() in r['gpu_name'].lower():
                    is_match_gpu = True
                    
                if target_model is not None and any(target_model.lower() in m.lower() for m in exact_models):
                    is_match_model = True

                if target_gpu or target_model:
                    if (target_gpu and is_match_gpu) or (target_model and is_match_model):
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
                    if r['version']: msg += f"v{r['version']} | "
                    if r['gpu_name']: msg += f"GPU: {r['gpu_name']} | "
                    mets = r.get("metrics", {})
                    if mets.get("model_count"): msg += f"Models: {mets['model_count']} | "
                    if mets.get("max_model_params"): msg += f"Max Params: {mets['max_model_params']}B | "
                    if mets.get("vram_free_gb") is not None: msg += f"VRAM Free: {mets['vram_free_gb']:.1f}GB"
                    
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
    target_gpu = next((sys.argv[i+1] for i, arg in enumerate(sys.argv) if arg == "--target-gpu" and i+1 < len(sys.argv)), None)
    target_model = next((sys.argv[i+1] for i, arg in enumerate(sys.argv) if arg == "--target-model" and i+1 < len(sys.argv)), None)

    queries = [
        ("port:8188 html:\"ComfyUI\"", 8188, Service.comfyui),
        ("port:11434 html:\"Ollama\"", 11434, Service.ollama)
    ]
    
    async with httpx.AsyncClient() as client:
        for query, port, service in queries:
            print(f"=== Starting scan for {service.value} ===")
            page = 1
            while True:
                ips = await scrape_shodan_page(query, page, client)
                if not ips:
                    print(f"[-] No IPs found on page {page}, stopping {service.value} scan.")
                    break
                    
                found_target = await process_ips(ips, port, service, force_rescan, target_gpu, target_model)
                if found_target:
                    # We only alert once for the target, then stop scraping this service
                    break
                    
                # If we are NOT in infinite target tracking mode, we just stop after page 2
                if not target_gpu and not target_model and page >= 2:
                    break
                
                if page >= MAX_PAGES:
                    print(f"[!] Reached max page cap ({MAX_PAGES}), stopping.")
                    await send_telegram_message(f"⚠️ Reached max page cap ({MAX_PAGES}) without finding target. Stopping.")
                    break
                    
                page += 1
                await asyncio.sleep(2) # be nice to Shodan HTML

if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.run(main())
