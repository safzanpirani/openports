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
    allow_methods=["*"] ,
    allow_headers=["*"] ,
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


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


@app.post("/api/scan/shodan", dependencies=[Depends(require_admin)])
async def trigger_shodan_scan(
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    limit: int | None = None,
):
    # Run in background so the HTTP request returns quickly.
    # Note: for heavier workloads, split scanner into a separate worker process.
    async def _runner():
        # new session for background task
        from sqlmodel import Session as _Session
        from .db import engine

        with _Session(engine) as s:
            await run_shodan_scan(s, limit=limit)

    background.add_task(asyncio.create_task, _runner())
    return {"status": "scheduled"}


# If you build the frontend into frontend/dist and copy it next to backend, we can serve it.
try:
    app.mount("/", StaticFiles(directory="../frontend/dist", html=True), name="frontend")
except Exception:
    # dev mode: frontend runs separately
    pass
