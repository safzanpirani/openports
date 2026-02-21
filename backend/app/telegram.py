from __future__ import annotations

import asyncio
import httpx
from typing import Callable, Awaitable

from .config import settings


async def send_telegram_message(text: str) -> None:
    """Send a message via Telegram Bot API.

    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
    """

    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(url, json=payload)
        except Exception:
            pass


async def poll_telegram_updates(on_command: Callable[[str], Awaitable[None]]) -> None:
    """Continuously poll the Telegram API for updates and route commands."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                res = await client.get(url, params={"offset": offset, "timeout": 20})
                if res.status_code == 200:
                    data = res.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            offset = max(offset, update["update_id"] + 1)
                            msg = update.get("message", {})
                            chat_id = msg.get("chat", {}).get("id")
                            text = msg.get("text", "")
                            
                            if str(chat_id) == str(settings.TELEGRAM_CHAT_ID) and text.startswith("/"):
                                await on_command(text.strip())
            except Exception:
                pass
            
            await asyncio.sleep(1)
