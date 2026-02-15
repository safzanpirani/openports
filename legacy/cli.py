from scanner import scan_network
import ipaddress
import shodan
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from typing import Optional

load_dotenv()


app = typer.Typer()
console = Console()

def parse_target(target: str) -> List[str]:
    """Parses a target string (IP or CIDR) into a list of IPs."""
    try:
        # Check if it's a network (CIDR)
        network = ipaddress.ip_network(target, strict=False)
        return [str(ip) for ip in network.hosts()]
    except ValueError:
        pass
    
    try:
        # Check if it's a single IP
        ip = ipaddress.ip_address(target)
        return [str(ip)]
    except ValueError:
        console.print(f"[red]Invalid IP or CIDR: {target}[/red]")
        return []

@app.command()
def scan(target: str = typer.Argument(..., help="IP address or CIDR range (e.g. 192.168.1.0/24)"), 
         json: bool = typer.Option(False, "--json", "-j", help="Output in JSON format")):
    """
    Scans the given target for ComfyUI (8188) and Ollama (11434) instances.
    """
    ips = parse_target(target)
    if not ips:
        return

    console.print(f"[bold green]Scanning {len(ips)} IPs...[/bold green]")
    
    # Run async scan
    results = asyncio.run(scan_network(ips))
    
    if json:
        import json as json_lib
        console.print(json_lib.dumps(results, indent=2))
    else:
        if not results:
            console.print("[yellow]No services found.[/yellow]")
            return

        table = Table(title="Scan Results")
        table.add_column("IP Address", style="cyan")
        table.add_column("Port", style="magenta")
        table.add_column("Service", style="green")
        
        for res in results:
            table.add_row(res["ip"], str(res["port"]), res["service"])
            
        console.print(table)


@app.command()
def shodan_scan(query: str = typer.Argument(..., help="Query to search on Shodan"), 
               limit: int = typer.Option(100, "--limit", "-l"),
               json: bool = typer.Option(False, "--json", "-j")):
    """
    Search Shodan for targets and verify them with our scanner.
    """
    api_key = os.getenv("SHODAN_API_KEY")
    if not api_key:
        console.print("[red]SHODAN_API_KEY not found in environment.[/red]")
        return

    try:
        api = shodan.Shodan(api_key)
        console.print(f"[bold cyan]Searching Shodan for '{query}'...[/bold cyan]")
        results = api.search(query, limit=limit)
        
        ips = [match['ip_str'] for match in results.get('matches', [])]
        if not ips:
            console.print("[yellow]No results found on Shodan.[/yellow]")
            return
            
        console.print(f"[green]Found {len(ips)} potential targets on Shodan. Verifying...[/green]")
        
        # Verify with our scanner
        verified_results = asyncio.run(scan_network(ips))
        
        if json:
            import json as json_lib
            console.print(json_lib.dumps(verified_results, indent=2))
        else:
            if not verified_results:
                console.print("[yellow]No active services confirmed from Shodan results.[/yellow]")
                return

            table = Table(title="Confirmed Services (via Shodan)")
            table.add_column("IP Address", style="cyan")
            table.add_column("Port", style="magenta")
            table.add_column("Service", style="green")
            
            for res in verified_results:
                table.add_row(res["ip"], str(res["port"]), res["service"])
                
            console.print(table)
            
    except shodan.APIError as e:
        console.print(f"[red]Shodan API Error: {e}[/red]")

if __name__ == "__main__":
    app()
