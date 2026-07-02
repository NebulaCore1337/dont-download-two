#!/usr/bin/env python3
"""Парсит все диалоги и показывает ID / название / тип."""
import asyncio, os
from pathlib import Path
from telethon import TelegramClient
from telethon.sessions import StringSession

# Прямая загрузка из .env
env_path = Path.home() / "AppData" / "Local" / "hermes" / ".env"
if env_path.exists():
    for line in env_path.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
SESSION = os.environ.get("TELEGRAM_SESSION_STRING_PERSONAL", "")

print(f"API_ID: {API_ID}, HASH: {API_HASH[:8]}..., SESSION: {SESSION[:20]}...")

async def main():
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH, proxy={
        "proxy_type": "socks5", "addr": "127.0.0.1", "port": 10808, "rdns": True,
    })
    await client.start()
    me = await client.get_me()
    print(f"\n✅ {me.first_name} (@{me.username})\n")
    print(f"{'ID':<16} {'Тип':<10} {'📌':>2} {'Название'}")
    print("-" * 60)
    async for dialog in client.iter_dialogs(limit=100):
        dtype = type(dialog.entity).__name__
        pin = "📌" if dialog.pinned else "  "
        unread = f" ({dialog.unread_count})" if dialog.unread_count else ""
        print(f"{dialog.id:<16} {dtype:<10} {pin} {dialog.name or '?'}{unread}")
    await client.disconnect()

asyncio.run(main())
