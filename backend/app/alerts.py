"""Standing alert evaluation. Called from scanner._upsert_instance after
emitting change rows. Best-effort — never raises through the caller.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from .models import Alert, Instance
from .models_summary import model_names
from .telegram import send_telegram_message


log = logging.getLogger("openports.alerts")


def _filter_matches_instance(filt: dict[str, Any], inst: Instance) -> bool:
    svc = filt.get("service")
    if svc and inst.service.value != svc:
        return False
    gpu = (filt.get("gpu") or "").strip().lower()
    if gpu:
        if not inst.gpu_name or gpu not in inst.gpu_name.lower():
            return False
    min_vram = filt.get("min_vram")
    if min_vram is not None:
        if inst.vram_total_gb is None or inst.vram_total_gb < float(min_vram):
            return False
    min_params = filt.get("min_max_params")
    if min_params is not None:
        if inst.max_model_params is None or inst.max_model_params < float(min_params):
            return False
    country_want = (filt.get("country") or "").strip().lower()
    if country_want:
        sh = inst.shodan or {}
        loc = sh.get("location") if isinstance(sh, dict) else None
        country = loc.get("country_name") if isinstance(loc, dict) else None
        if not country or country.lower() != country_want:
            return False
    provider_want = filt.get("provider")
    if provider_want:
        if provider_want == "vps":
            if inst.provider in (None, "residential", "unknown"):
                return False
        elif provider_want == "residential":
            if inst.provider != "residential":
                return False
        elif provider_want == "unknown":
            if inst.provider is not None:
                return False
        else:
            if inst.provider != provider_want:
                return False
    return True


def _model_substring_match(filt: dict[str, Any], names: list[str]) -> bool:
    needle = (filt.get("model") or "").strip().lower()
    if not needle:
        return True
    return any(needle in n.lower() for n in names)


def _format_alert_message(alert: Alert, inst: Instance, extra: str = "") -> str:
    bits = [
        f"🔔 {alert.name}",
        f"{inst.service.value} · http://{inst.ip}:{inst.port}",
    ]
    facts: list[str] = []
    if inst.gpu_name:
        facts.append(inst.gpu_name)
    if inst.vram_total_gb:
        facts.append(f"{inst.vram_total_gb:.0f}GB")
    if inst.model_count:
        facts.append(f"{inst.model_count} models")
    if inst.max_model_params:
        facts.append(f"max {inst.max_model_params:.0f}B")
    if facts:
        bits.append(" · ".join(facts))
    if extra:
        bits.append(extra)
    return "\n".join(bits)


def _send(text: str) -> None:
    """Fire-and-forget telegram dispatch, safe from sync callers."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(send_telegram_message(text))
            return
    except RuntimeError:
        pass
    try:
        asyncio.run(send_telegram_message(text))
    except Exception:
        log.exception("failed to send telegram alert")


def evaluate_alerts(
    session: Session,
    inst: Instance,
    *,
    is_first_seen: bool,
    alive_flipped: bool | None,
    models_added: list[str] | None,
) -> int:
    """Match the just-upserted instance against every enabled Alert. Fires a
    Telegram message per match. Returns the number of alerts fired.

    Inputs reflect what just changed:
      - is_first_seen: True if InstanceChange `first_seen` was just emitted.
      - alive_flipped: True/False if alive transitioned, else None.
      - models_added: list of newly-added model names if a `models_changed`
        row was emitted with non-empty `added`, else None.
    """

    fired = 0
    try:
        alerts = list(session.exec(select(Alert).where(Alert.enabled == True)).all())
    except Exception:
        return 0
    if not alerts:
        return 0

    inst_models = model_names(inst.service, inst.models)

    for a in alerts:
        try:
            filt = a.filter_json or {}
            kind = a.kind

            if kind == "new_instance" and not is_first_seen:
                continue
            if kind == "alive_changed":
                if alive_flipped is None:
                    continue
                want_alive = filt.get("alive")
                if want_alive is not None and bool(want_alive) != bool(alive_flipped):
                    continue
            if kind == "models_added" and not models_added:
                continue

            if not _filter_matches_instance(filt, inst):
                continue

            # Model substring: for models_added, match against just-added names.
            # Otherwise, match the current full model list.
            if kind == "models_added":
                if not _model_substring_match(filt, models_added or []):
                    continue
            else:
                if not _model_substring_match(filt, inst_models):
                    continue

            extra = ""
            if kind == "models_added" and models_added:
                preview = ", ".join(models_added[:5])
                extra = f"+{len(models_added)} models: {preview}"
            elif kind == "alive_changed":
                extra = "came back alive" if alive_flipped else "went down"
            elif kind == "new_instance":
                extra = "first seen"

            _send(_format_alert_message(a, inst, extra))
            a.last_fired_at = datetime.utcnow()
            a.fired_count = (a.fired_count or 0) + 1
            session.add(a)
            fired += 1
        except Exception:
            log.exception("alert eval failed for #%s", a.id)
            continue

    if fired:
        try:
            session.commit()
        except Exception:
            session.rollback()
    return fired
