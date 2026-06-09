"""Telegram bot command handlers."""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any

from sqlalchemy import Text, cast, func
from sqlmodel import Session, select

from .config import settings
from .models import Alert, Instance, InstanceCheck, InstanceChange, ScanRun, Service
from .models_summary import model_names
from .recheck import run_recheck
from .scanner import run_shodan_scan
from .telegram import send_telegram_message


log = logging.getLogger("openports.commands")


HELP = """available commands

/help — this list
/ping — pong
/status — counts (total/alive, by service, stale)
/top [n] — top n alive instances by VRAM (default 10)
/find key=value [...] — multi-axis filter (service, gpu, model, country, provider, version, vram>=N, params>=N)
/diff <id> — show recent changes for an instance
/show <id> — full metadata card for one instance
/refresh <id> — re-fingerprint one instance now and report updated state
/runs [n] — last n scan runs (default 5)
/catalog [svc] [q] — top model names by instance count
/alerts — list standing alerts
/alert add|edit|toggle|del — manage alert rules (see /alert for syntax)
/scan — trigger one shodan scan across all 16 supported ports
/recheck [n] [force] [alive] — re-fingerprint up to n stored instances
/scrape ... — shodan web bot scraper (existing)"""


def _running_loop_or_new() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.new_event_loop()


def _run_in_executor(loop: asyncio.AbstractEventLoop, fn, *args) -> None:
    loop.run_in_executor(None, fn, *args)


def _parse_service(value: str) -> Service | None:
    want = value.strip().lower()
    for service in Service:
        if service.value.lower() == want:
            return service
    return None


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
        per_service: dict[str, tuple[int, int]] = {}
        for svc in Service:
            rows = [r for r in all_rows if r.service == svc]
            if rows:
                per_service[svc.value] = (len(rows), sum(1 for r in rows if r.is_alive))
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(hours=24)
        stale = sum(1 for r in all_rows if r.last_checked_at < cutoff)
        last_run = s.exec(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(1)).first()
        last_line = (
            f"last scan {last_run.source} @ {last_run.started_at.isoformat(timespec='minutes')}"
            if last_run
            else "no scans yet"
        )

    if per_service:
        ordered = sorted(per_service.items(), key=lambda kv: kv[1][0], reverse=True)
        svc_line = "\n".join(f"{name}: {tot}/{al}" for name, (tot, al) in ordered)
    else:
        svc_line = "(no instances yet)"

    return (
        f"status\n"
        f"total: {total} ({alive} alive)\n"
        f"by service (total/alive):\n{svc_line}\n"
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


async def _cmd_diff(engine, instance_id: int, n: int = 10) -> str:
    with Session(engine) as s:
        inst = s.get(Instance, instance_id)
        if inst is None:
            return f"no instance with id {instance_id}"
        rows = list(s.exec(
            select(InstanceChange)
            .where(InstanceChange.instance_id == instance_id)
            .order_by(InstanceChange.at.desc())
            .limit(n)
        ).all())
    header = f"changes for #{instance_id} ({inst.service.value} · http://{inst.ip}:{inst.port})"
    if not rows:
        return f"{header}\n(no changes recorded)"
    lines = [header]
    for r in rows:
        ts = r.at.strftime("%m-%d %H:%M")
        if r.kind == "first_seen":
            lines.append(f"{ts} · first seen")
        elif r.kind == "alive_changed":
            new = (r.after or {}).get("alive")
            lines.append(f"{ts} · {'came back alive' if new else 'went down'}")
        elif r.kind == "version_changed":
            b = (r.before or {}).get("version") or "—"
            a = (r.after or {}).get("version") or "—"
            lines.append(f"{ts} · version {b} → {a}")
        elif r.kind == "gpu_changed":
            b = (r.before or {}).get("gpu") or "—"
            a = (r.after or {}).get("gpu") or "—"
            lines.append(f"{ts} · gpu {b} → {a}")
        elif r.kind == "models_changed":
            added = (r.after or {}).get("added") or []
            removed = (r.after or {}).get("removed") or []
            lines.append(f"{ts} · models +{len(added)} −{len(removed)}")
        else:
            lines.append(f"{ts} · {r.kind}")
    return "\n".join(lines)


async def _cmd_alerts(engine) -> str:
    with Session(engine) as s:
        rows = list(s.exec(select(Alert).order_by(Alert.created_at.desc())).all())
    if not rows:
        return "no alerts configured.\nadd one in the web ui at /alerts."
    lines = ["alerts:"]
    for a in rows:
        flag = "✓" if a.enabled else "✗"
        f = a.filter_json or {}
        bits = [f"#{a.id} {flag} [{a.kind}] {a.name}"]
        kvs = [f"{k}={v}" for k, v in f.items() if v not in (None, "", 0)]
        if kvs:
            bits.append(" / " + ", ".join(kvs))
        bits.append(f" · fired {a.fired_count}")
        lines.append("".join(bits))
    return "\n".join(lines)


_FIND_KEYS = {"gpu", "model", "country", "service", "provider", "vram", "params", "version"}


def _parse_find_args(args: list[str]) -> tuple[dict[str, Any], str | None]:
    """Parse /find arguments into a filter dict.

    Supports two grammars:
    - legacy: ``/find gpu <value>`` / ``/find model <value>`` / ``/find country <value>``
    - multi-axis: ``/find service=ollama gpu=5090 vram>=24 country="United States"``

    Returns ({key: ('eq'|'gte'|'lte', value)}, error_or_None).
    """
    if not args:
        return {}, "usage: /find key=value [key=value ...]\nkeys: " + ", ".join(sorted(_FIND_KEYS))

    # Legacy: first token is a known key, rest is the value.
    if len(args) >= 2 and args[0].lower() in _FIND_KEYS and "=" not in args[0] and ">" not in args[0] and "<" not in args[0]:
        return {args[0].lower(): ("eq", " ".join(args[1:]))}, None

    out: dict[str, tuple[str, Any]] = {}
    for tok in args:
        op = "eq"
        sep = "="
        if ">=" in tok:
            sep, op = ">=", "gte"
        elif "<=" in tok:
            sep, op = "<=", "lte"
        elif ">" in tok:
            sep, op = ">", "gte"
        elif "<" in tok:
            sep, op = "<", "lte"
        elif "=" in tok:
            sep, op = "=", "eq"
        else:
            return {}, f"can't parse '{tok}' (expected key=value or key>n)"
        k, _, v = tok.partition(sep)
        k = k.lower().strip()
        v = v.strip()
        if k not in _FIND_KEYS:
            return {}, f"unknown key '{k}'. valid: {', '.join(sorted(_FIND_KEYS))}"
        if op != "eq" and k not in {"vram", "params"}:
            return {}, f"key '{k}' only supports = (not >/<)"
        out[k] = (op, v)
    return out, None


async def _cmd_find(engine, args: list[str]) -> str:
    filters, err = _parse_find_args(args)
    if err:
        return err

    with Session(engine) as s:
        stmt = select(Instance).where(Instance.is_alive == True)
        for key, (op, val) in filters.items():
            vlow = val.lower() if isinstance(val, str) else val
            if key == "gpu":
                stmt = stmt.where(func.lower(func.coalesce(Instance.gpu_name, "")).like(f"%{vlow}%"))
            elif key == "model":
                stmt = stmt.where(func.lower(cast(Instance.models, Text)).like(f"%{vlow}%"))
            elif key == "country":
                stmt = stmt.where(
                    func.lower(func.coalesce(
                        func.json_extract(Instance.shodan, "$.location.country_name"), ""
                    )) == vlow
                )
            elif key == "service":
                svc = _parse_service(str(val))
                if svc is None:
                    return f"unknown service '{val}'. valid: {', '.join(s.value for s in Service)}"
                stmt = stmt.where(Instance.service == svc)
            elif key == "provider":
                if vlow == "vps":
                    stmt = stmt.where(
                        Instance.provider.is_not(None),
                        Instance.provider != "residential",
                        Instance.provider != "unknown",
                    )
                else:
                    stmt = stmt.where(Instance.provider == vlow)
            elif key == "version":
                stmt = stmt.where(func.lower(func.coalesce(Instance.version, "")).like(f"%{vlow}%"))
            elif key in {"vram", "params"}:
                try:
                    n = float(val)
                except ValueError:
                    return f"'{key}' value must be a number, got '{val}'"
                col = Instance.vram_total_gb if key == "vram" else Instance.max_model_params
                if op == "gte":
                    stmt = stmt.where(col >= n)
                elif op == "lte":
                    stmt = stmt.where(col <= n)
                else:
                    stmt = stmt.where(col == n)
        stmt = stmt.order_by(Instance.last_seen_at.desc()).limit(50)
        rows = list(s.exec(stmt).all())

    summary = " ".join(f"{k}{('=' if op == 'eq' else '>=' if op == 'gte' else '<=')}{v}" for k, (op, v) in filters.items())
    return _format_rows(rows, f"find {summary} ({len(rows)} found)")


_ALERT_KINDS = {"new_instance", "models_added", "alive_changed"}
_ALERT_FILTER_KEYS = {"service", "gpu", "min_vram", "min_max_params", "model", "country", "provider", "alive"}


def _parse_alert_kvs(tokens: list[str]) -> tuple[dict[str, Any], str | None]:
    """Parse `kind=foo gpu=bar min_vram=24` style tokens. Returns (parsed, error).

    Numeric coercion for min_vram / min_max_params; bool for alive (1/0/true/false).
    """
    out: dict[str, Any] = {}
    for tok in tokens:
        if "=" not in tok:
            return {}, f"can't parse '{tok}' (expected key=value)"
        k, _, v = tok.partition("=")
        k = k.lower().strip()
        v = v.strip()
        if k not in _ALERT_FILTER_KEYS and k != "kind" and k != "name":
            return {}, f"unknown alert key '{k}'. valid: kind, name, {', '.join(sorted(_ALERT_FILTER_KEYS))}"
        if k == "kind":
            if v not in _ALERT_KINDS:
                return {}, f"unknown kind '{v}'. valid: {', '.join(sorted(_ALERT_KINDS))}"
            out["kind"] = v
        elif k == "service":
            svc = _parse_service(v)
            if svc is None:
                return {}, f"unknown service '{v}'. valid: {', '.join(s.value for s in Service)}"
            out["service"] = svc.value
        elif k in ("min_vram", "min_max_params"):
            try:
                out[k] = float(v)
            except ValueError:
                return {}, f"'{k}' must be a number, got '{v}'"
        elif k == "alive":
            if v.lower() in ("1", "true", "yes", "up", "alive"):
                out["alive"] = True
            elif v.lower() in ("0", "false", "no", "down"):
                out["alive"] = False
            else:
                return {}, f"'alive' must be 1/0/true/false, got '{v}'"
        else:
            out[k] = v
    return out, None


def _alert_summary(a: Alert) -> str:
    flag = "✓" if a.enabled else "✗"
    f = a.filter_json or {}
    bits = [f"#{a.id} {flag} [{a.kind}] {a.name}"]
    kvs = [f"{k}={v}" for k, v in f.items() if v not in (None, "", 0)]
    if kvs:
        bits.append(" / " + ", ".join(kvs))
    bits.append(f" · fired {a.fired_count}")
    return "".join(bits)


async def _cmd_alert_add(engine, args: list[str]) -> str:
    if not args:
        return "usage: /alert add <name> kind=<k> [filter_key=value ...]\nkinds: new_instance, models_added, alive_changed"
    # First token is the name (quote it for spaces).
    name = args[0]
    kvs, err = _parse_alert_kvs(args[1:])
    if err:
        return err
    kind = kvs.pop("kind", None)
    if not kind:
        return "kind=<new_instance|models_added|alive_changed> is required"
    filter_json = {k: v for k, v in kvs.items() if v not in (None, "")}
    with Session(engine) as s:
        a = Alert(name=name, kind=kind, filter_json=filter_json, enabled=True)
        s.add(a)
        s.commit()
        s.refresh(a)
    return "alert created\n" + _alert_summary(a)


async def _cmd_alert_edit(engine, alert_id: int, args: list[str]) -> str:
    if not args:
        return "usage: /alert edit <id> [name=<n>] [kind=<k>] [filter_key=value ...]"
    kvs, err = _parse_alert_kvs(args)
    if err:
        return err
    with Session(engine) as s:
        a = s.get(Alert, alert_id)
        if a is None:
            return f"no alert with id {alert_id}"
        if "name" in kvs:
            a.name = kvs.pop("name")
        if "kind" in kvs:
            a.kind = kvs.pop("kind")
        if kvs:
            new_filter = dict(a.filter_json or {})
            for k, v in kvs.items():
                if v in (None, ""):
                    new_filter.pop(k, None)
                else:
                    new_filter[k] = v
            a.filter_json = new_filter
        s.add(a)
        s.commit()
        s.refresh(a)
    return "alert updated\n" + _alert_summary(a)


async def _cmd_alert_toggle(engine, alert_id: int) -> str:
    with Session(engine) as s:
        a = s.get(Alert, alert_id)
        if a is None:
            return f"no alert with id {alert_id}"
        a.enabled = not a.enabled
        s.add(a)
        s.commit()
        s.refresh(a)
    return ("enabled" if a.enabled else "disabled") + "\n" + _alert_summary(a)


async def _cmd_alert_del(engine, alert_id: int) -> str:
    with Session(engine) as s:
        a = s.get(Alert, alert_id)
        if a is None:
            return f"no alert with id {alert_id}"
        name = a.name
        s.delete(a)
        s.commit()
    return f"deleted alert #{alert_id} ({name})"


async def _cmd_show(engine, instance_id: int) -> str:
    with Session(engine) as s:
        inst = s.get(Instance, instance_id)
        if inst is None:
            return f"no instance with id {instance_id}"
        last_check = s.exec(
            select(InstanceCheck)
            .where(InstanceCheck.instance_id == instance_id)
            .order_by(InstanceCheck.checked_at.desc())
            .limit(1)
        ).first()
    state = "alive" if inst.is_alive else "down"
    sh = inst.shodan or {}
    loc = (sh.get("location") if isinstance(sh, dict) else None) or {}
    country = loc.get("country_name")
    city = loc.get("city")
    org = sh.get("org") if isinstance(sh, dict) else None
    asn = sh.get("asn") if isinstance(sh, dict) else None
    sources = ", ".join(inst.discovery_sources or []) or "—"
    geo = " / ".join(p for p in (country, city) if p) or "—"

    lines = [
        f"#{inst.id} · {inst.service.value} · http://{inst.ip}:{inst.port} · {state}",
        f"version: {inst.version or '—'}",
        f"gpu: {inst.gpu_name or '—'}",
    ]
    if inst.vram_total_gb is not None:
        free = f" / {inst.vram_free_gb:.0f}GB free" if inst.vram_free_gb is not None else ""
        lines.append(f"vram: {inst.vram_total_gb:.0f}GB{free}")
    if inst.model_count is not None:
        mp = f" · max {inst.max_model_params:.0f}B" if inst.max_model_params else ""
        ctx = f" · ctx {inst.max_context}" if inst.max_context else ""
        lines.append(f"models: {inst.model_count}{mp}{ctx}")
    lines.append(f"provider: {inst.provider or '—'}  · asn: {asn or '—'}")
    lines.append(f"location: {geo}  · org: {org or '—'}")
    if inst.reverse_dns:
        lines.append(f"reverse dns: {inst.reverse_dns}")
    lines.append(f"first seen: {inst.first_seen_at.isoformat(timespec='minutes')}")
    lines.append(f"last seen:  {inst.last_seen_at.isoformat(timespec='minutes')}")
    lines.append(f"last check: {inst.last_checked_at.isoformat(timespec='minutes')}")
    lines.append(f"discovered via: {sources}")
    if inst.last_error:
        lines.append(f"last error: {inst.last_error}")
    if last_check and last_check.error and not inst.last_error:
        lines.append(f"last check error: {last_check.error}")
    return "\n".join(lines)


async def _cmd_refresh(engine, instance_id: int) -> str:
    """Re-fingerprint a single instance synchronously and return an updated card."""

    import httpx

    from .fingerprints import verify_for_service
    from .scanner import _upsert_instance

    with Session(engine) as s:
        inst = s.get(Instance, instance_id)
        if inst is None:
            return f"no instance with id {instance_id}"
        service = inst.service
        ip = inst.ip
        port = inst.port
        shodan_match = inst.shodan

    base_url = f"http://{ip}:{port}"
    timeout = httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            ok, meta, models, version, gpu_name, metrics = await verify_for_service(service, base_url, client)
    except Exception as e:
        log.exception("/refresh verify failed for %s %s:%s", service.value, ip, port)
        return f"refresh failed: {type(e).__name__}: {e}"

    with Session(engine) as s:
        _upsert_instance(
            s, service, ip, port, ok, meta, models, version, gpu_name,
            shodan_match=shodan_match, metrics=metrics,
        )

    return await _cmd_show(engine, instance_id)


async def _cmd_runs(engine, n: int = 5) -> str:
    with Session(engine) as s:
        rows = list(s.exec(
            select(ScanRun).order_by(ScanRun.started_at.desc()).limit(n)
        ).all())
    if not rows:
        return "no scan runs yet"
    lines = [f"last {len(rows)} runs"]
    for r in rows:
        ts = r.started_at.strftime("%m-%d %H:%M")
        finished = "running" if r.finished_at is None else "done"
        cands = r.candidates if r.candidates is not None else "—"
        verified = r.verified if r.verified is not None else "—"
        new = r.new_instances if r.new_instances is not None else "—"
        line = f"#{r.id} · {ts} · {r.source} · cand={cands} verified={verified} new={new} · {finished}"
        if r.error:
            line += f" · err: {r.error[:80]}"
        lines.append(line)
    return "\n".join(lines)


async def _cmd_catalog(engine, service_filter: str | None, query: str | None, top_n: int = 20) -> str:
    """Aggregate model names across alive instances; optional service + substring filter."""

    counts: dict[str, int] = {}
    qsvc: Service | None = None
    if service_filter:
        qsvc = _parse_service(service_filter)
        if qsvc is None:
            return f"unknown service '{service_filter}'. valid: {', '.join(s.value for s in Service)}"
    with Session(engine) as s:
        stmt = select(Instance).where(Instance.is_alive == True)
        if qsvc is not None:
            stmt = stmt.where(Instance.service == qsvc)
        rows = list(s.exec(stmt).all())
    needle = (query or "").lower().strip() or None
    for r in rows:
        for name in model_names(r.service, r.models) or []:
            if needle and needle not in name.lower():
                continue
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return f"no models found{' for ' + qsvc.value if qsvc else ''}"
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    header = f"top {len(ordered)} models" + (f" for {qsvc.value}" if qsvc else "") + (f" matching '{query}'" if needle else "")
    lines = [header]
    for name, c in ordered:
        lines.append(f"{c:>4} · {name}")
    if len(counts) > top_n:
        lines.append(f"… +{len(counts) - top_n} more")
    return "\n".join(lines)


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
        await send_telegram_message(await _cmd_find(engine, args))
        return

    if cmd == "/diff":
        if len(args) < 1:
            await send_telegram_message("usage: /diff <instance_id> [n]")
            return
        try:
            iid = int(args[0])
        except ValueError:
            await send_telegram_message("instance id must be a number")
            return
        n = 10
        if len(args) >= 2:
            try:
                n = max(1, min(50, int(args[1])))
            except ValueError:
                pass
        await send_telegram_message(await _cmd_diff(engine, iid, n))
        return

    if cmd == "/show":
        if len(args) < 1:
            await send_telegram_message("usage: /show <instance_id>")
            return
        try:
            iid = int(args[0])
        except ValueError:
            await send_telegram_message("instance id must be a number")
            return
        await send_telegram_message(await _cmd_show(engine, iid))
        return

    if cmd == "/refresh":
        if len(args) < 1:
            await send_telegram_message("usage: /refresh <instance_id>")
            return
        try:
            iid = int(args[0])
        except ValueError:
            await send_telegram_message("instance id must be a number")
            return
        await send_telegram_message(f"re-fingerprinting #{iid}…")
        await send_telegram_message(await _cmd_refresh(engine, iid))
        return

    if cmd == "/runs":
        n = 5
        if args:
            try:
                n = max(1, min(20, int(args[0])))
            except ValueError:
                pass
        await send_telegram_message(await _cmd_runs(engine, n))
        return

    if cmd == "/catalog":
        svc = args[0] if args else None
        q = " ".join(args[1:]) if len(args) >= 2 else None
        # Allow `/catalog <query>` with no service: if first arg isn't a known service, treat it as the query.
        if svc and _parse_service(svc) is None:
            q = " ".join(args)
            svc = None
        await send_telegram_message(await _cmd_catalog(engine, svc, q))
        return

    if cmd == "/alerts":
        await send_telegram_message(await _cmd_alerts(engine))
        return

    if cmd == "/alert":
        if not args:
            await send_telegram_message(
                "usage:\n"
                "  /alert add <name> kind=<k> [filter_key=value ...]\n"
                "  /alert edit <id> [name=<n>] [kind=<k>] [filter_key=value ...]\n"
                "  /alert toggle <id>\n"
                "  /alert del <id>\n"
                "kinds: new_instance, models_added, alive_changed\n"
                "filter keys: service, gpu, min_vram, min_max_params, model, country, provider, alive"
            )
            return
        sub = args[0].lower()
        rest = args[1:]
        if sub == "add":
            await send_telegram_message(await _cmd_alert_add(engine, rest))
            return
        if sub in ("edit", "toggle", "del", "delete"):
            if not rest:
                await send_telegram_message(f"usage: /alert {sub} <id> ...")
                return
            try:
                aid = int(rest[0])
            except ValueError:
                await send_telegram_message("alert id must be a number")
                return
            if sub == "edit":
                await send_telegram_message(await _cmd_alert_edit(engine, aid, rest[1:]))
            elif sub == "toggle":
                await send_telegram_message(await _cmd_alert_toggle(engine, aid))
            else:
                await send_telegram_message(await _cmd_alert_del(engine, aid))
            return
        await send_telegram_message(f"unknown subcommand '{sub}'. try: add | edit | toggle | del")
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
