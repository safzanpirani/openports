"""Telegram bot command handlers."""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any

from sqlalchemy import Text, cast, func
from sqlmodel import Session, select

from .config import settings
from .models import Instance, ScanRun, Service
from .recheck import run_recheck
from .scanner import run_shodan_scan
from .telegram import send_telegram_message


log = logging.getLogger("openports.commands")


HELP = """available commands

/help — this list
/ping — pong
/status — counts (total/alive, by service, stale)
/top [n] — top n alive instances by VRAM (default 10)
/find gpu <name> — list alive instances with that gpu (substring)
/find model <name> — list alive instances with that model (substring)
/find country <name> — list alive instances in that country
/scan — trigger one shodan scan (port:8188 or port:11434)
/recheck [n] [force] [alive] — re-fingerprint up to n stored instances
/scrape ... — shodan web bot scraper (existing)"""


def _running_loop_or_new() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.new_event_loop()


def _run_in_executor(loop: asyncio.AbstractEventLoop, fn, *args) -> None:
    loop.run_in_executor(None, fn, *args)


def _scan_job(_: Any = None) -> None:
    from .db import engine

    with Session(engine) as s:
        asyncio.run(run_shodan_scan(s))


def _recheck_job(only_stale: bool, only_alive: bool, limit: int | None) -> None:
    from .db import engine

    with Session(engine) as s:
        asyncio.run(run_recheck(s, only_stale=only_stale, only_alive=only_alive, limit=limit))


def _ip_url(inst: Instance) -> str:
    return f"http://{inst.ip}:{inst.port}"


def _row_line(inst: Instance) -> str:
    parts = [inst.service.value, _ip_url(inst)]
    if inst.gpu_name:
        parts.append(inst.gpu_name)
    if inst.vram_total_gb:
        parts.append(f"{inst.vram_total_gb:.0f}GB")
    if inst.model_count:
        parts.append(f"{inst.model_count} models")
    if inst.max_model_params:
        parts.append(f"max {inst.max_model_params:.0f}B")
    return " · ".join(parts)


def _format_rows(rows: list[Instance], header: str, max_lines: int = 25) -> str:
    if not rows:
        return f"{header}\n(no matches)"
    lines = [header]
    for r in rows[:max_lines]:
        lines.append(_row_line(r))
    if len(rows) > max_lines:
        lines.append(f"… +{len(rows) - max_lines} more")
    return "\n".join(lines)


async def _cmd_status(engine) -> str:
    with Session(engine) as s:
        all_rows = list(s.exec(select(Instance)).all())
        total = len(all_rows)
        alive = sum(1 for r in all_rows if r.is_alive)
        comfy = sum(1 for r in all_rows if r.service == Service.comfyui)
        ollama = sum(1 for r in all_rows if r.service == Service.ollama)
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(hours=24)
        stale = sum(1 for r in all_rows if r.last_checked_at < cutoff)
        last_run = s.exec(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(1)).first()
        last_line = (
            f"last scan {last_run.source} @ {last_run.started_at.isoformat(timespec='minutes')}"
            if last_run
            else "no scans yet"
        )

    return (
        f"status\n"
        f"total: {total} ({alive} alive)\n"
        f"comfyui: {comfy}  ·  ollama: {ollama}\n"
        f"stale (>24h since last check): {stale}\n"
        f"{last_line}\n"
        f"sched: scan/{settings.SCAN_INTERVAL_MINUTES}min recheck/{settings.RECHECK_INTERVAL_MINUTES}min"
    )


async def _cmd_top(engine, n: int) -> str:
    with Session(engine) as s:
        rows = list(s.exec(
            select(Instance)
            .where(Instance.is_alive == True)
            .order_by(Instance.vram_total_gb.is_(None), Instance.vram_total_gb.desc())
            .limit(n)
        ).all())
    return _format_rows(rows, f"top {n} alive by vram", max_lines=n)


async def _cmd_find(engine, key: str, value: str) -> str:
    key_l = key.lower()
    val_l = value.lower()
    with Session(engine) as s:
        stmt = select(Instance).where(Instance.is_alive == True)
        if key_l == "gpu":
            stmt = stmt.where(func.lower(func.coalesce(Instance.gpu_name, "")).like(f"%{val_l}%"))
        elif key_l == "model":
            stmt = stmt.where(
                func.lower(cast(Instance.models, Text)).like(f"%{val_l}%")
            )
        elif key_l == "country":
            stmt = stmt.where(
                func.lower(func.coalesce(
                    func.json_extract(Instance.shodan, "$.location.country_name"), ""
                )) == val_l
            )
        else:
            return f"unknown find key '{key}'. try gpu, model, or country."
        stmt = stmt.order_by(Instance.last_seen_at.desc()).limit(50)
        rows = list(s.exec(stmt).all())
    return _format_rows(rows, f"find {key}={value!r} ({len(rows)} found)")


async def handle_command(text: str) -> None:
    """Top-level dispatcher used by the telegram poller."""

    from .db import engine

    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    if not parts:
        return
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd == "/ping":
        await send_telegram_message("pong")
        return

    if cmd == "/help":
        await send_telegram_message(HELP)
        return

    if cmd == "/status":
        await send_telegram_message(await _cmd_status(engine))
        return

    if cmd == "/top":
        n = 10
        if args:
            try:
                n = max(1, min(50, int(args[0])))
            except ValueError:
                pass
        await send_telegram_message(await _cmd_top(engine, n))
        return

    if cmd == "/find":
        if len(args) < 2:
            await send_telegram_message("usage: /find gpu|model|country <value>")
            return
        key = args[0]
        value = " ".join(args[1:])
        await send_telegram_message(await _cmd_find(engine, key, value))
        return

    if cmd == "/scan":
        await send_telegram_message("starting shodan scan…")
        loop = _running_loop_or_new()
        loop.run_in_executor(None, _scan_job)
        await send_telegram_message("scan scheduled. results land as it finishes.")
        return

    if cmd == "/recheck":
        force = any(a.lower() == "force" for a in args)
        only_alive = any(a.lower() == "alive" for a in args)
        n: int | None = None
        for a in args:
            if a.lower() in {"force", "alive"}:
                continue
            try:
                n = int(a)
                break
            except ValueError:
                continue
        only_stale = not force
        await send_telegram_message(
            f"starting recheck (only_stale={only_stale} only_alive={only_alive} limit={n or 'all'})…"
        )
        loop = _running_loop_or_new()
        loop.run_in_executor(None, _recheck_job, only_stale, only_alive, n)
        await send_telegram_message("recheck scheduled. results land as it finishes.")
        return

    # Fall through — let the legacy scrape handler in main.py handle it.
    raise NotImplementedError(cmd)
