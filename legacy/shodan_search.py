import shodan
import os
from typing import List

# Constants
SHODAN_API_KEY = os.getenv("SHODAN_API_KEY")

def get_shodan_ips(query: str, limit: int = 100) -> List[str]:
    """
    Searches Shodan for IPs matching the query.
    Requires SHODAN_API_KEY environment variable.
    """
    if not SHODAN_API_KEY:
        raise ValueError("SHODAN_API_KEY environment variable not set.")

    api = shodan.Shodan(SHODAN_API_KEY)
    ips = []
    
    try:
        # Search Shodan
        results = api.search(query, limit=limit)
        for result in results['matches']:
            ips.append(result['ip_str'])
    except shodan.APIError as e:
        print(f"Error: {e}")
        
    return ips

def search_comfyui_candidates(limit: int = 50) -> List[str]:
    """Search specifically for ComfyUI candidates (port 8188)."""
    return get_shodan_ips("port:8188", limit)

def search_ollama_candidates(limit: int = 50) -> List[str]:
    """Search specifically for Ollama candidates (port 11434)."""
    return get_shodan_ips("port:11434", limit)
