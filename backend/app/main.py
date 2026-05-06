from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timedelta

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, text
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


async def _telegram_handler(text_in: str) -> None:
    from sqlmodel import Session as _Session
    from .db import engine
    from sqlmodel import select

    cmd = text_in.split()[0].lower()
    if cmd == "/scan":
        await send_telegram_message("Starting Shodan scan...")
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
        parts = text_in.split()
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


_SORTABLE = {
    "last_seen_at": Instance.last_seen_at,
    "first_seen_at": Instance.first_seen_at,
    "vram_total_gb": Instance.vram_total_gb,
    "vram_free_gb": Instance.vram_free_gb,
    "model_count": Instance.model_count,
    "max_model_params": Instance.max_model_params,
    "max_context": Instance.max_context,
    "node_count": Instance.node_count,
}


def _build_filtered_query(
    *,
    service: Service | None,
    alive: bool | None,
    provider: str | None,
    q: str | None,
    model: str | None,
    gpu: str | None,
    country: str | None,
    since_hours: int | None,
    min_vram: float | None,
    sort_by: str | None,
    sort_dir: str | None,
):
    stmt = select(Instance)

    if service:
        stmt = stmt.where(Instance.service == service)
    if alive is not None:
        stmt = stmt.where(Instance.is_alive == alive)
    if provider:
        if provider == "vps":
            stmt = stmt.where(Instance.provider.notin_(["residential", "unknown", None]))
        elif provider == "residential":
            stmt = stmt.where(Instance.provider == "residential")
        elif provider == "unknown":
            stmt = stmt.where(Instance.provider.is_(None))
        else:
            stmt = stmt.where(Instance.provider == provider)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Instance.ip).like(like),
                func.lower(func.coalesce(Instance.version, "")).like(like),
                func.lower(func.coalesce(Instance.gpu_name, "")).like(like),
                func.lower(func.coalesce(Instance.title, "")).like(like),
                func.lower(func.coalesce(Instance.reverse_dns, "")).like(like),
            )
        )
    if model:
        like = f"%{model.lower()}%"
        # SQLite: cast JSON column to text and substring-match (case-insensitive).
        stmt = stmt.where(func.lower(func.cast(Instance.models, text("TEXT"))).like(like))
    if gpu:
        like = f"%{gpu.lower()}%"
        stmt = stmt.where(func.lower(func.coalesce(Instance.gpu_name, "")).like(like))
    if country:
        # Country lives in shodan.location.country_name. Use SQLite JSON1.
        stmt = stmt.where(
            func.lower(func.coalesce(
                func.json_extract(Instance.shodan, "$.location.country_name"), ""
            )) == country.lower()
        )
    if since_hours is not None and since_hours > 0:
        cutoff = datetime.utcnow() - timedelta(hours=since_hours)
        stmt = stmt.where(Instance.last_seen_at >= cutoff)
    if min_vram is not None and min_vram > 0:
        stmt = stmt.where(Instance.vram_total_gb >= min_vram)

    sort_col = _SORTABLE.get(sort_by or "last_seen_at", Instance.last_seen_at)
    if (sort_dir or "desc").lower() == "asc":
        stmt = stmt.order_by(sort_col.asc())
    else:
        stmt = stmt.order_by(sort_col.desc())

    return stmt


@app.get("/api/instances/count")
def count_instances(
    session: Session = Depends(get_session),
    service: Service | None = None,
    alive: bool | None = None,
    provider: str | None = None,
    q: str | None = None,
    model: str | None = None,
    gpu: str | None = None,
    country: str | None = None,
    since_hours: int | None = Query(default=None, ge=1, le=24 * 365),
    min_vram: float | None = Query(default=None, ge=0),
):
    stmt = _build_filtered_query(
        service=service, alive=alive, provider=provider, q=q, model=model,
        gpu=gpu, country=country, since_hours=since_hours, min_vram=min_vram,
        sort_by=None, sort_dir=None,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    n = session.exec(count_stmt).one()
    if isinstance(n, tuple):
        n = n[0]
    return {"count": int(n or 0)}


@app.get("/api/instances")
def list_instances(
    session: Session = Depends(get_session),
    service: Service | None = None,
    alive: bool | None = None,
    provider: str | None = None,
    q: str | None = None,
    model: str | None = None,
    gpu: str | None = None,
    country: str | None = None,
    since_hours: int | None = Query(default=None, ge=1, le=24 * 365),
    min_vram: float | None = Query(default=None, ge=0),
    sort_by: str | None = Query(default=None),
    sort_dir: str | None = Query(default=None, pattern="^(asc|desc)$"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    stmt = _build_filtered_query(
        service=service, alive=alive, provider=provider, q=q, model=model,
        gpu=gpu, country=country, since_hours=since_hours, min_vram=min_vram,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    stmt = stmt.offset(offset).limit(limit)
    return session.exec(stmt).all()


@app.get("/api/instances/{instance_id}")
def get_instance(instance_id: int, session: Session = Depends(get_session)):
    inst = session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    return inst


@app.post("/api/instances/{instance_id}/refresh", dependencies=[Depends(require_admin)])
async def refresh_instance(instance_id: int, session: Session = Depends(get_session)):
    """Re-fingerprint a single instance now and return the updated row."""

    inst = session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    import httpx
    from .fingerprints import verify_comfyui, verify_ollama
    from .scanner import _upsert_instance

    base_url = f"http://{inst.ip}:{inst.port}"
    timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        if inst.service == Service.comfyui:
            ok, meta, models, version, gpu_name, metrics = await verify_comfyui(base_url, client)
            updated, _created = _upsert_instance(
                session, Service.comfyui, inst.ip, inst.port, ok, meta, models, version, gpu_name,
                shodan_match=inst.shodan, metrics=metrics,
            )
        else:
            ok, meta, models, version, metrics = await verify_ollama(base_url, client)
            updated, _created = _upsert_instance(
                session, Service.ollama, inst.ip, inst.port, ok, meta, models, version, None,
                shodan_match=inst.shodan, metrics=metrics,
            )

    return updated


@app.get("/api/stats")
def stats(session: Session = Depends(get_session)):
    """Aggregate counts for the dashboard."""

    all_rows = session.exec(select(Instance)).all()
    total = len(all_rows)
    alive_count = sum(1 for r in all_rows if r.is_alive)

    by_service: dict[str, dict[str, int]] = {}
    for s in Service:
        rows = [r for r in all_rows if r.service == s]
        by_service[s.value] = {
            "total": len(rows),
            "alive": sum(1 for r in rows if r.is_alive),
        }

    by_provider: dict[str, int] = {}
    for r in all_rows:
        key = r.provider or "unknown"
        by_provider[key] = by_provider.get(key, 0) + 1

    now = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    recent_24h = sum(1 for r in all_rows if r.first_seen_at >= cutoff_24h)
    recent_7d = sum(1 for r in all_rows if r.first_seen_at >= cutoff_7d)

    last_run = session.exec(
        select(ScanRun).order_by(ScanRun.started_at.desc()).limit(1)
    ).first()

    return {
        "total": total,
        "alive": alive_count,
        "by_service": by_service,
        "by_provider": by_provider,
        "recent_24h": recent_24h,
        "recent_7d": recent_7d,
        "last_run": last_run,
    }


@app.get("/api/instances/distinct/{field}")
def distinct_values(field: str, session: Session = Depends(get_session)):
    """Distinct values for a small set of filterable fields."""

    if field == "gpu":
        rows = session.exec(
            select(Instance.gpu_name, func.count())
            .where(Instance.gpu_name.is_not(None))
            .group_by(Instance.gpu_name)
        ).all()
        return [{"value": v, "count": c} for v, c in rows if v]

    if field == "provider":
        rows = session.exec(
            select(Instance.provider, func.count()).group_by(Instance.provider)
        ).all()
        return [{"value": v or "unknown", "count": c} for v, c in rows]

    if field == "version":
        rows = session.exec(
            select(Instance.version, func.count())
            .where(Instance.version.is_not(None))
            .group_by(Instance.version)
        ).all()
        return [{"value": v, "count": c} for v, c in rows if v]

    if field == "country":
        # Pull country from shodan JSON. SQLite JSON1.
        country_expr = func.json_extract(Instance.shodan, "$.location.country_name")
        rows = session.exec(
            select(country_expr, func.count())
            .where(country_expr.is_not(None))
            .group_by(country_expr)
        ).all()
        return [{"value": v, "count": c} for v, c in rows if v]

    raise HTTPException(status_code=400, detail=f"Unknown distinct field: {field}")


_CSV_FIELDS = [
    "id", "service", "ip", "port", "is_alive", "provider", "country",
    "version", "gpu_name", "vram_total_gb", "vram_free_gb",
    "model_count", "max_model_params", "max_context",
    "first_seen_at", "last_seen_at", "last_checked_at", "reverse_dns",
]


def _country_of(inst: Instance) -> str | None:
    sh = inst.shodan or {}
    loc = sh.get("location") if isinstance(sh, dict) else None
    if isinstance(loc, dict):
        return loc.get("country_name")
    return None


@app.get("/api/instances.csv")
def export_csv(
    session: Session = Depends(get_session),
    service: Service | None = None,
    alive: bool | None = None,
    provider: str | None = None,
    q: str | None = None,
    model: str | None = None,
    gpu: str | None = None,
    country: str | None = None,
    since_hours: int | None = Query(default=None, ge=1, le=24 * 365),
    min_vram: float | None = Query(default=None, ge=0),
    sort_by: str | None = None,
    sort_dir: str | None = Query(default=None, pattern="^(asc|desc)$"),
):
    stmt = _build_filtered_query(
        service=service, alive=alive, provider=provider, q=q, model=model,
        gpu=gpu, country=country, since_hours=since_hours, min_vram=min_vram,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    rows = session.exec(stmt).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_CSV_FIELDS)
    for r in rows:
        w.writerow([
            r.id, r.service.value if r.service else "",
            r.ip, r.port, int(r.is_alive), r.provider or "", _country_of(r) or "",
            r.version or "", r.gpu_name or "",
            f"{r.vram_total_gb:.2f}" if r.vram_total_gb is not None else "",
            f"{r.vram_free_gb:.2f}" if r.vram_free_gb is not None else "",
            r.model_count if r.model_count is not None else "",
            r.max_model_params if r.max_model_params is not None else "",
            r.max_context if r.max_context is not None else "",
            r.first_seen_at.isoformat() if r.first_seen_at else "",
            r.last_seen_at.isoformat() if r.last_seen_at else "",
            r.last_checked_at.isoformat() if r.last_checked_at else "",
            r.reverse_dns or "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="openports-instances.csv"'},
    )


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
