"""Helper to print chat IDs from Telegram updates.

Usage:
  cd backend
  export TELEGRAM_BOT_TOKEN='...'
  python3 tools/get_telegram_chat_id.py

Notes:
- You must send at least one message to your bot first (e.g. /start).
- If you previously set a webhook, run:
    curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/deleteWebhook"
"""

from __future__ import annotations

import os
from typing import Any

import httpx


def _iter_updates(data: dict[str, Any]):
    res = data.get("result")
    if not isinstance(res, list):
        return
    for item in res:
        if not isinstance(item, dict):
            continue
        # private/group messages
        msg = item.get("message")
        if isinstance(msg, dict):
            yield msg
        # channels
        ch = item.get("channel_post")
        if isinstance(ch, dict):
            yield ch


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN env var not set")

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    r = httpx.get(url, timeout=15.0)
    r.raise_for_status()
    data = r.json()

    chats: dict[int, dict[str, Any]] = {}
    for msg in _iter_updates(data):
        chat = msg.get("chat")
        if not isinstance(chat, dict):
            continue
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            continue
        chats[chat_id] = {
            "type": chat.get("type"),
            "title": chat.get("title"),
            "username": chat.get("username"),
            "first_name": chat.get("first_name"),
            "last_name": chat.get("last_name"),
        }

    if not chats:
        print("No updates found. Send a message to the bot and try again.")
        return

    print("Found chat IDs (set TELEGRAM_CHAT_ID to one of these):")
    for chat_id, info in chats.items():
        label = info.get("title") or info.get("username") or info.get("first_name") or "(unknown)"
        print(f"- {chat_id}  ({info.get('type')})  {label}")


if __name__ == "__main__":
    main()
