#!/usr/bin/env python3
"""
Telegram AI Auto-Reply MCP Server
MCP-сервер с интегрированным AI-автоответчиком через iamhc.cn (OpenAI-compat).
Слушает входящие сообщения → строит контекст → запрашивает AI → отвечает сам.
Hermes может в любой момент вмешаться через tools (send/read/list).
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from telethon import TelegramClient, events
from telethon.tl.types import User

# Пробуем httpx, иначе стандартные (так как httpx может быть не установлен)
try:
    import httpx
    _has_httpx = True
except ImportError:
    _has_httpx = False
    import urllib.request
    import urllib.error

# ==================== КОНФИГ ====================

# Подгружаем переменные из ~/.hermes/.env (там живут ключи Hermes)
def _load_hermes_env():
    try:
        from pathlib import Path
        env_path = Path(os.path.expanduser("~")) / "AppData" / "Local" / "hermes" / ".env"
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())
    except Exception:
        pass


_load_hermes_env()

API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
PHONE = os.environ.get("TG_PHONE", "")

# AI API
AI_API_KEY = os.environ.get("AI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.iamhc.cn/v1")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")

SESSION_FILE = os.path.join(os.path.dirname(__file__), "auto_reply_session")
LOG_FILE = os.path.join(os.path.dirname(__file__), "auto_reply_log.json")

# Контакты для AI-автоответа (юзернеймы без @)
AI_CONTACTS = [
    "QEENSOP395",    # Соня
    "eshkertq998",   # Ваня
    "iddan787",       # Айдан
    "delayjitter36",  # Павел Серебряников
    "Ddnl7",  # Кириллица
]

# Персоналии для промпта (опционально — помогает AI понять кто есть кто)
CONTACT_INFO = {
    "QEENSOP395": {"name": "Соня", "relation": "девушка", "notes": "любит мемы, иногда злится если не отвечаю"},
    "eshkertq998": {"name": "Ваня", "relation": "друг", "notes": "из Иркутска, любит трещать про игры и машины"},
    "iddan787": {"name": "Айдан", "relation": "знакомый", "notes": "тихий, редко пишет, ведёт бизнес"},
    "delayjitter36": {"name": "Паша", "relation": "знакомый", "notes": "Павел Серебряников"},
}

# AI-персона автоответчика (как AI должен отвечать)
AI_PERSONA = os.environ.get("AI_PERSONA",
    "Ты помогаешь другу отвечать на сообщения. Отвечай кратко, по-человечески, с юмором. "
    "Ты его лучший друг, который временно берёт телефон. Не говори что ты AI, просто пишь как человек."
)

DEFAULT_REPLY = "Привет! Сейчас меня нет, но я скоро отвечу. Это автоответчик 🤖"

# Статичные ответы на крайний случай (если AI-сервис лёг)
CUSTOM_REPLIES = {
    "QEENSOP395": "Сонечка, я сейчас занят, но скоро отвечу ❤️",
    "eshkertq998": "Вань, я щас занят, напишу чуть позже",
    "iddan787": "Привет, сейчас не могу ответить, напишу позже",
}

REPLY_DELAY = 5           # секунд перед ответом
AI_CONTEXT_MESSAGES = 10  # сколько последних сообщений подаём в контекст
_AI_ENABLED = True        # вкл/выкл AI-автоответа

# ==================== LLM КЛИЕНТ ====================

def _call_ai_api(messages: list[dict], max_retries: int = 2) -> str:
    """Делает запрос к AI API и возвращает текст ответа."""
    if not AI_API_KEY:
        return None

    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.8,
    }

    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }

    if _has_httpx:
        for attempt in range(max_retries + 1):
            try:
                response = httpx.post(
                    f"{AI_BASE_URL}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                if attempt == max_retries:
                    print(f"[AI ERROR] {e}", file=sys.stderr)
                    return None
                time.sleep(1.5 ** attempt)
    else:
        # Fallback на urllib
        req = urllib.request.Request(
            url=f"{AI_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[AI ERROR] {e}", file=sys.stderr)
            return None
    return None


def build_ai_messages(history: list[dict], contact_info: dict) -> list[dict]:
    """Строит массив messages для OpenAI API из истории диалога."""
    system_msg = AI_PERSONA
    if contact_info:
        system_msg += (
            f"\n\nКонтакт: {contact_info.get('name', 'Незнакомец')} "
            f"({contact_info.get('relation', '')}). {contact_info.get('notes', '')}"
        )

    messages = [{"role": "system", "content": system_msg}]

    for msg in history:
        role = "user" if msg.get("from_me") else "assistant"
        messages.append({"role": role, "content": msg.get("text", "")})

    return messages


# ==================== ТЕЛЕГРАМ КЛИЕНТ ====================

client = TelegramClient(
    SESSION_FILE,
    API_ID,
    API_HASH,
    proxy={
        "proxy_type": "socks5",
        "addr": "127.0.0.1",
        "port": 10808,
        "rdns": True,
    },
    connection_retries=None,  # бесконечные попытки
    retry_delay=5,
)
_client_ready = asyncio.Event()
_recent_messages = []  # буфер последних входящих

# Храним контекст диалогов: {chat_id: [messages]}
_dialog_contexts: dict[int, list[dict]] = {}


def log_message(data: dict):
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
    logs.append(data)
    if len(logs) > 500:
        logs = logs[-500:]
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


async def get_dialog_history(chat_id: int, limit: int = AI_CONTEXT_MESSAGES) -> list[dict]:
    """Загружает последние сообщения из диалога для контекста."""
    try:
        entity = await client.get_entity(chat_id)
        messages = await client.get_messages(entity, limit=limit)
        history = []
        me = await client.get_me()
        for msg in reversed(messages):
            sender = await msg.get_sender()
            is_me = sender.id == me.id if sender else False
            history.append({
                "from_me": is_me,
                "text": msg.text or "[медиа]",
                "date": msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else "",
            })
        return history
    except Exception as e:
        print(f"[ERROR get_dialog_history] {e}", file=sys.stderr)
        return []


@client.on(events.NewMessage(incoming=True))
async def on_new_message(event):
    """Обработчик входящих сообщений — AI-автоответ."""
    global _AI_ENABLED

    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.self:
        return

    username = sender.username or ""
    display_name = sender.first_name or "Unknown"
    text = event.raw_text or ""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = {
        "time": timestamp,
        "from": display_name,
        "username": f"@{username}" if username else "no_username",
        "chat_id": event.chat_id,
        "text": text[:500],
        "private": event.is_private,
    }
    _recent_messages.append(entry)
    if len(_recent_messages) > 100:
        _recent_messages = _recent_messages[-100:]

    log_message(entry)

    # AI-автоответ только в личке, включён, и контакт в списке
    if event.is_private and _AI_ENABLED and username and username.lower() in [c.lower() for c in AI_CONTACTS]:
        chat_id = event.chat_id

        # 1. Получаем историю диалога
        history = await get_dialog_history(chat_id, limit=AI_CONTEXT_MESSAGES)

        # 2. Добавляем текущее сообщение пользователя
        history.append({
            "from_me": False,
            "text": text,
            "date": timestamp,
        })

        # 3. Строем промпт
        contact_info = CONTACT_INFO.get(username, {})
        ai_messages = build_ai_messages(history, contact_info)

        # 4. Запрашиваем AI
        ai_reply = _call_ai_api(ai_messages)

        if ai_reply:
            await asyncio.sleep(REPLY_DELAY)
            try:
                await event.reply(ai_reply)
                entry["ai_replied"] = True
                entry["ai_reply_text"] = ai_reply[:200]
            except Exception as e:
                entry["ai_reply_error"] = str(e)
        else:
            # Fallback на статичный ответ если AI сломался
            await asyncio.sleep(REPLY_DELAY)
            reply = CUSTOM_REPLIES.get(username, DEFAULT_REPLY)
            try:
                await event.reply(reply)
                entry["auto_replied"] = True
            except Exception as e:
                entry["auto_reply_error"] = str(e)


# ==================== MCP СЕРВЕР ====================

app = Server("telegram-auto-reply")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="telegram_status",
            description="Проверяет статус подключения к Telegram. Показывает, подключён ли клиент и кто залогинен.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="telegram_recent_messages",
            description="Показывает последние входящие сообщения (буфер). Уведомляет о новых.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Сколько последних сообщений показать (по умолчанию 10)",
                        "default": 10,
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="telegram_send_message",
            description="Отправляет сообщение в Telegram по username или chat_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Юзернейм (например @QEENSOP395) или chat_id (число как строка)",
                    },
                    "message": {
                        "type": "string",
                        "description": "Текст сообщения для отправки",
                    },
                },
                "required": ["to", "message"],
            },
        ),
        Tool(
            name="telegram_read_dialog",
            description="Читает последние сообщения из конкретного диалога.",
            inputSchema={
                "type": "object",
                "properties": {
                    "with": {
                        "type": "string",
                        "description": "Юзернейм (например @eshkertq998) или chat_id",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Сколько сообщений прочитать (по умолчанию 20)",
                        "default": 20,
                    },
                },
                "required": ["with"],
            },
        ),
        Tool(
            name="telegram_list_dialogs",
            description="Показывает список диалогов (чатов) с количеством непрочитанных.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Сколько диалогов показать (по умолчанию 20)",
                        "default": 20,
                    },
                    "unread_only": {
                        "type": "boolean",
                        "description": "Только с непрочитанными сообщениями",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="telegram_toggle_auto_reply",
            description="Включает или выключает AI-автоответчик.",
            inputSchema={
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "true — включить автоответ, false — выключить",
                    },
                },
                "required": ["enabled"],
            },
        ),
        Tool(
            name="telegram_set_auto_reply_text",
            description="Меняет текст AI-персоны автоответчика.",
            inputSchema={
                "type": "object",
                "properties": {
                    "persona": {
                        "type": "string",
                        "description": "Новый промпт для AI (как он должен отвечать)",
                    },
                },
                "required": ["persona"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    global _AI_ENABLED, AI_PERSONA

    if not _client_ready.is_set():
        return [TextContent(type="text", text="❌ Telegram клиент ещё не подключён. Подожди пару секунд.")]

    # --- telegram_status ---
    if name == "telegram_status":
        me = await client.get_me()
        status = "🟢 ВКЛЮЧЁН" if _AI_ENABLED else "🔴 ВЫКЛЮЧЁН"
        contacts = ", ".join(f"@{c}" for c in AI_CONTACTS)
        return [TextContent(
            type="text",
            text=(
                f"✅ Подключён как: {me.first_name} (ID: {me.id})\n"
                f"🤖 AI автоответчик: {status}\n"
                f"📋 Контакты: {contacts}\n"
                f"🧠 AI модель: {AI_MODEL}\n"
                f"🔗 AI URL: {AI_BASE_URL}"
            ),
        )]

    # --- telegram_recent_messages ---
    if name == "telegram_recent_messages":
        limit = arguments.get("limit", 10)
        msgs = _recent_messages[-limit:] if _recent_messages else []
        if not msgs:
            return [TextContent(type="text", text="📭 Нет новых сообщений.")]
        lines = []
        for m in reversed(msgs):
            arrow = "📩" if m.get("private") else "💬"
            replied = " ✅AI" if m.get("ai_replied") else ""
            lines.append(f"{arrow} [{m['time']}] {m['from']} ({m.get('username','')}): {m['text'][:150]}{replied}")
        return [TextContent(type="text", text="\n".join(lines))]

    # --- telegram_send_message ---
    if name == "telegram_send_message":
        to = arguments["to"]
        message = arguments["message"]
        try:
            if to.startswith("@"):
                entity = await client.get_entity(to)
            else:
                entity = await client.get_entity(int(to))
            await client.send_message(entity, message)
            return [TextContent(type="text", text=f"✅ Сообщение отправлено -> {to}")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Ошибка отправки: {e}")]

    # --- telegram_read_dialog ---
    if name == "telegram_read_dialog":
        target = arguments["with"]
        limit = arguments.get("limit", 20)
        try:
            if target.startswith("@"):
                entity = await client.get_entity(target)
            else:
                entity = await client.get_entity(int(target))
            messages = await client.get_messages(entity, limit=limit)
            lines = []
            for msg in reversed(messages):
                sender = await msg.get_sender()
                name_str = sender.first_name if sender and hasattr(sender, 'first_name') else "Unknown"
                me = await client.get_me()
                prefix = "👉" if sender and sender.id == me.id else "📩"
                lines.append(f"{prefix} [{msg.date.strftime('%H:%M')}] {name_str}: {msg.text or '[медиа]'}")
            return [TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Ошибка чтения: {e}")]

    # --- telegram_list_dialogs ---
    if name == "telegram_list_dialogs":
        limit = arguments.get("limit", 20)
        unread_only = arguments.get("unread_only", False)
        try:
            dialogs = await client.get_dialogs(limit=limit)
            lines = []
            for d in dialogs:
                if unread_only and d.unread_count == 0:
                    continue
                name = d.name or "Unknown"
                unread = f" ({d.unread_count} непрочитанных)" if d.unread_count > 0 else ""
                muted = " 🔇" if getattr(d, 'is_muted', False) else ""
                lines.append(f"💬 {name}{unread}{muted} — ID: {d.id}")
            if not lines:
                return [TextContent(type="text", text="📭 Нет диалогов с непрочитанными.")]
            return [TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Ошибка: {e}")]

    # --- telegram_toggle_auto_reply ---
    if name == "telegram_toggle_auto_reply":
        _AI_ENABLED = arguments["enabled"]
        status = "🟢 ВКЛЮЧЁН" if _AI_ENABLED else "🔴 ВЫКЛЮЧЁН"
        return [TextContent(type="text", text=f"AI автоответчик: {status}")]

    # --- telegram_set_auto_reply_text ---
    if name == "telegram_set_auto_reply_text":
        AI_PERSONA = arguments["persona"]
        return [TextContent(type="text", text=f"✅ AI-персона обновлена:\n{AI_PERSONA[:200]}...")]

    return [TextContent(type="text", text=f"❌ Неизвестный инструмент: {name}")]


# ==================== ЗАПУСК ====================

async def main():
    if not API_ID or not API_HASH or not PHONE:
        print("❌ Установи TG_API_ID, TG_API_HASH, TG_PHONE", file=sys.stderr)
        sys.exit(1)

    # Проверка AI ключей
    if AI_API_KEY:
        print(f"🧠 AI автоответчик настроен: {AI_BASE_URL}", file=sys.stderr)
    else:
        print("⚠️ AI_API_KEY не задан — автоответ будет статичным", file=sys.stderr)

    # Запускаем Telegram клиент в фоне
    await client.start(phone=PHONE)
    me = await client.get_me()
    print(f"✅ Telegram: {me.first_name} (ID: {me.id})", file=sys.stderr)
    _client_ready.set()

    # Запускаем MCP сервер (stdio)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
