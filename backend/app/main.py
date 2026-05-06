from __future__ import annotations

import asyncio

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from .config import settings
from .db import get_session, init_db
from .models import Instance, ScanRun, Service
from .scanner import run_shodan_scan
from .security import require_admin


app = FastAPI(title="openports")

cors_origins = settings.cors_origins_list or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials="*" not in cors_origins,
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
            alive_count = len(
                s.exec(select(Instance).where(Instance.is_alive == True)).all()
            )
            total = len(s.exec(select(Instance)).all())
        await send_telegram_message(
            f"Status:\nTotal instances: {total}\nAlive instances: {alive_count}"
        )
    elif cmd == "/scrape":
        parts = text.split()
        control_tokens = {"gpu", "model", "force", "-page", "--page"}
        force_rescan = any(p.lower() == "force" for p in parts)
        target_gpu = None
        target_model = None
        max_pages: int | None = None

        i = 1
        while i < len(parts):
            token = parts[i].lower()
            if token in {"gpu", "model"}:
                j = i + 1
                value_parts: list[str] = []
                while j < len(parts) and parts[j].lower() not in control_tokens:
                    value_parts.append(parts[j])
                    j += 1
                value = " ".join(value_parts).strip() if value_parts else None
                if token == "gpu":
                    target_gpu = value
                else:
                    target_model = value
                i = j
                continue
            if token in {"-page", "--page"} and i + 1 < len(parts):
                try:
                    parsed_pages = int(parts[i + 1])
                    if parsed_pages > 0:
                        max_pages = parsed_pages
                except ValueError:
                    pass
                i += 2
                continue
            i += 1

        msg_action = "Starting Shodan web bot scraper"
        if target_gpu or target_model:
            msg_action += " (Target mode: chasing down"
            if target_gpu:
                msg_action += f" GPU='{target_gpu}'"
            if target_model:
                msg_action += f" Model='{target_model}'"
            if max_pages:
                msg_action += f" up to {max_pages} pages"
            else:
                msg_action += " up to 5 pages per provider"
            msg_action += ")..."
        else:
            page_window = max_pages or 5
            msg_action += f" (Page 1-{page_window} per provider)..."

        if force_rescan:
            msg_action += " [FORCE RESCAN ENABLED]"

        await send_telegram_message(msg_action)
        import subprocess
        import os
        import sys

        # Run the scraper as a subprocess so it doesn't block the async event loop
        # and has its own clean module setup
        script_path = os.path.join(
            os.path.dirname(__file__), "..", "tools", "shodan_scraper.py"
        )
        loop = asyncio.get_running_loop()

        def _run_scraper():
            args = [sys.executable, script_path]
            if force_rescan:
                args.append("--force")
            if target_gpu:
                args.extend(["--target-gpu", target_gpu])
            if target_model:
                args.extend(["--target-model", target_model])
            if max_pages:
                args.extend(["--max-pages", str(max_pages)])
            subprocess.run(args, check=False)

        loop.run_in_executor(None, _run_scraper)
        await send_telegram_message(
            "Scraper job scheduled (Check bot logs/chat for output)."
        )
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
    service: Service | None = None,
    alive: bool | None = None,
    provider: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    stmt = (
        select(Instance)
        .order_by(Instance.last_seen_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if service:
        stmt = stmt.where(Instance.service == service)
    if alive is not None:
        stmt = stmt.where(Instance.is_alive == alive)
    if provider:
        if provider == "vps":
            # "vps" means "any known cloud provider" (not residential, not unknown)
            stmt = stmt.where(Instance.provider.notin_(["residential", "unknown", None]))
        elif provider == "residential":
            stmt = stmt.where(Instance.provider == "residential")
        elif provider == "unknown":
            stmt = stmt.where(Instance.provider.is_(None))
        else:
            stmt = stmt.where(Instance.provider == provider)
    return session.exec(stmt).all()


@app.get("/api/instances/{instance_id}")
def get_instance(instance_id: int, session: Session = Depends(get_session)):
    inst = session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    return inst


@app.get("/api/scan/runs")
def list_runs(
    session: Session = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=500),
):
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
    limit: int | None = Query(default=None, ge=1, le=10000),
):
    # Run in background so the HTTP request returns quickly.
    # Note: for heavier workloads, split scanner into a separate worker process.
    background.add_task(_run_shodan_scan_job, limit)
    return {"status": "scheduled"}


# If you build the frontend into frontend/dist and copy it next to backend, we can serve it.
try:
    app.mount(
        "/", StaticFiles(directory="../frontend/dist", html=True), name="frontend"
    )
except Exception:
    # dev mode: frontend runs separately
    pass
