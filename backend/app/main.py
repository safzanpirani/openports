from __future__ import annotations

import asyncio

from fastapi import BackgroundTasks, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from .config import settings
from .db import get_session, init_db
from .models import Instance, ScanRun
from .scanner import run_shodan_scan
from .security import require_admin


app = FastAPI(title="openports")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from .telegram import poll_telegram_updates, send_telegram_message

async def _telegram_handler(text: str) -> None:
    from sqlmodel import Session as _Session
    from .db import engine
    from sqlmodel import select

    cmd = text.split()[0].lower()
    if cmd == "/scan":
        await send_telegram_message("Starting Shodan scan...")
        # Schedule in background
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _run_shodan_scan_job, None)
        await send_telegram_message("Scan job scheduled.")
    elif cmd == "/status":
        with _Session(engine) as s:
            alive_count = len(s.exec(select(Instance).where(Instance.is_alive == True)).all())
            total = len(s.exec(select(Instance)).all())
        await send_telegram_message(f"Status:\nTotal instances: {total}\nAlive instances: {alive_count}")
    elif cmd == "/scrape":
        parts = text.split()
        # Check for exact word "force" (not substring match, to avoid e.g. "reinforce")
        lower_parts = [p.lower() for p in parts]
        force_rescan = "force" in lower_parts
        target_gpu = None
        target_model = None
        
        for i, p in enumerate(parts):
            if p.lower() == "gpu" and i + 1 < len(parts):
                target_gpu = parts[i+1]
            elif p.lower() == "model" and i + 1 < len(parts):
                target_model = parts[i+1]

        msg_action = "Starting Shodan web bot scraper"
        if target_gpu or target_model:
            msg_action += f" (Infinite mode: chasing down"
            if target_gpu: msg_action += f" GPU='{target_gpu}'"
            if target_model: msg_action += f" Model='{target_model}'"
            msg_action += ")..."
        else:
            msg_action += " (Page 1-2)..."

        if force_rescan:
            msg_action += " [FORCE RESCAN ENABLED]"
            
        await send_telegram_message(msg_action)
        import subprocess
        import os
        import sys
        
        # Run the scraper as a subprocess so it doesn't block the async event loop
        # and has its own clean module setup
        script_path = os.path.join(os.path.dirname(__file__), "..", "tools", "shodan_scraper.py")
        loop = asyncio.get_running_loop()
        
        def _run_scraper():
            args = [sys.executable, script_path]
            if force_rescan:
                args.append("--force")
            if target_gpu:
                args.extend(["--target-gpu", target_gpu])
            if target_model:
                args.extend(["--target-model", target_model])
            subprocess.run(args, check=False)
            
        loop.run_in_executor(None, _run_scraper)
        await send_telegram_message("Scraper job scheduled (Check bot logs/chat for output).")
    elif cmd == "/ping":
        await send_telegram_message("pong")


async def _start_telegram_poller() -> None:
    await poll_telegram_updates(_telegram_handler)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    asyncio.create_task(_start_telegram_poller())


@app.get("/api/instances")
def list_instances(
    session: Session = Depends(get_session),
    service: str | None = None,
    alive: bool | None = None,
    limit: int = 200,
    offset: int = 0,
):
    stmt = select(Instance).order_by(Instance.last_seen_at.desc()).offset(offset).limit(limit)
    if service:
        stmt = stmt.where(Instance.service == service)  # type: ignore
    if alive is not None:
        stmt = stmt.where(Instance.is_alive == alive)
    return session.exec(stmt).all()


@app.get("/api/instances/{instance_id}")
def get_instance(instance_id: int, session: Session = Depends(get_session)):
    inst = session.get(Instance, instance_id)
    return inst


@app.get("/api/scan/runs")
def list_runs(session: Session = Depends(get_session), limit: int = 50):
    stmt = select(ScanRun).order_by(ScanRun.started_at.desc()).limit(limit)
    return session.exec(stmt).all()


def _run_shodan_scan_job(limit: int | None) -> None:
    """Run a Shodan scan in a background worker thread.

    Starlette BackgroundTasks run in a threadpool where there is no running event loop,
    so we use asyncio.run() here.
    """

    from sqlmodel import Session as _Session

    from .db import engine

    with _Session(engine) as s:
        asyncio.run(run_shodan_scan(s, limit=limit))


@app.post("/api/scan/shodan", dependencies=[Depends(require_admin)])
async def trigger_shodan_scan(
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    limit: int | None = None,
):
    # Run in background so the HTTP request returns quickly.
    # Note: for heavier workloads, split scanner into a separate worker process.
    background.add_task(_run_shodan_scan_job, limit)
    return {"status": "scheduled"}


# If you build the frontend into frontend/dist and copy it next to backend, we can serve it.
try:
    app.mount("/", StaticFiles(directory="../frontend/dist", html=True), name="frontend")
except Exception:
    # dev mode: frontend runs separately
    pass
