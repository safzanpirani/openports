import asyncio
import aiohttp
import socket
from typing import List, Dict, Optional

# Constants
TIMEOUT = 2  # Seconds to wait for connection/response
COMFYUI_PORT = 8188
OLLAMA_PORT = 11434

async def check_port(ip: str, port: int) -> bool:
    """Checks if a TCP port is open."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=TIMEOUT
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False

async def identify_service(session: aiohttp.ClientSession, ip: str, port: int) -> Optional[str]:
    """Identifies if the service on the port is ComfyUI or Ollama."""
    url = f"http://{ip}:{port}"
    try:
        # Try to identify based on port AND response
        if port == COMFYUI_PORT:
            # ComfyUI usually returns a specific HTML or JSON on /history
            try:
                async with session.get(f"{url}/history", timeout=TIMEOUT) as resp:
                    if resp.status == 200:
                         # Strong indicator for ComfyUI
                        return "ComfyUI"
            except:
                pass
            
            # Fallback: check root
            async with session.get(url, timeout=TIMEOUT) as resp:
                 if resp.status == 200:
                     text = await resp.text()
                     if "ComfyUI" in text or "window.comfyAPI" in text: # Heuristic
                         return "ComfyUI"

        elif port == OLLAMA_PORT:
            # Ollama root returns "Ollama is running"
            async with session.get(url, timeout=TIMEOUT) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    if "Ollama is running" in text:
                        return "Ollama"
            
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None
    
    return None

async def scan_target(session: aiohttp.ClientSession, ip: str) -> List[Dict]:
    """Scans a single IP for both services."""
    found_services = []
    
    # Check ComfyUI
    if await check_port(ip, COMFYUI_PORT):
        service = await identify_service(session, ip, COMFYUI_PORT)
        if service:
            found_services.append({"ip": ip, "port": COMFYUI_PORT, "service": service})
    
    # Check Ollama
    if await check_port(ip, OLLAMA_PORT):
        service = await identify_service(session, ip, OLLAMA_PORT)
        if service:
            found_services.append({"ip": ip, "port": OLLAMA_PORT, "service": service})
            
    return found_services

async def scan_network(ips: List[str]) -> List[Dict]:
    """Scans a list of IPs concurrently."""
    async with aiohttp.ClientSession() as session:
        tasks = [scan_target(session, ip) for ip in ips]
        results = await asyncio.gather(*tasks)
        # Flatten results
        return [item for sublist in results for item in sublist]

if __name__ == "__main__":
    # Quick test
    import sys
    
    async def main():
        target_ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
        print(f"Scanning {target_ip}...")
        results = await scan_network([target_ip])
        print("Found:", results)

    asyncio.run(main())
