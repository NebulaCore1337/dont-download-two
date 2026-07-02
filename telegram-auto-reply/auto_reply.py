#!/usr/bin/env python3
"""
Telegram AI Auto-Reply
Фоновый скрипт: слушает входящие → AI генерирует ответ → отправляет.
Использует StringSession (не нужен повторный логин) + SOCKS5 через xRay.
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import subprocess

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User, MessageMediaPhoto, MessageMediaDocument

# ==================== MEDIA ====================

try:
    from media import transcribe_audio, analyze_image
except ImportError:
    transcribe_audio = None
    analyze_image = None

# ==================== ЗАГРУЗКА ENV ====================

def _load_env(path: str):
    """Подгружает .env файл в os.environ"""
    p = Path(path)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Подгружаем ключи из Hermes .env
_load_env(Path.home() / "AppData" / "Local" / "hermes" / ".env")

# ==================== CONFIG.JSON ====================

CONFIG_FILE = Path(__file__).parent / "config.json"


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def _apply_config(cfg: dict):
    """Применяет настройки из config.json к глобальным переменным."""
    global AI_MODEL, AI_BASE_URL, REPLY_DELAY, SPAM_COOLDOWN, SPAM_MAX_PER_MINUTE
    global SLEEP_START_HOUR, SLEEP_END_HOUR, GROUP_CHAT_ID, GROUP_TRIGGER
    global GROUP_REQUIRE_MENTION, _MODE, _group_muted, AI_CONTACTS

    if cfg.get("ai_model"): AI_MODEL = cfg["ai_model"]
    if cfg.get("ai_base_url"): AI_BASE_URL = cfg["ai_base_url"]
    if cfg.get("reply_delay") is not None: REPLY_DELAY = cfg["reply_delay"]
    if cfg.get("spam_cooldown") is not None: SPAM_COOLDOWN = cfg["spam_cooldown"]
    if cfg.get("spam_max_per_minute") is not None: SPAM_MAX_PER_MINUTE = cfg["spam_max_per_minute"]
    if cfg.get("sleep_start_hour") is not None: SLEEP_START_HOUR = cfg["sleep_start_hour"]
    if cfg.get("sleep_end_hour") is not None: SLEEP_END_HOUR = cfg["sleep_end_hour"]
    if cfg.get("group_chat_id") is not None: GROUP_CHAT_ID = cfg["group_chat_id"]
    if cfg.get("group_trigger"): GROUP_TRIGGER = cfg["group_trigger"]
    if cfg.get("group_require_mention") is not None: GROUP_REQUIRE_MENTION = cfg["group_require_mention"]
    if cfg.get("mode") is not None: _MODE = cfg["mode"]
    if cfg.get("group_muted") is not None: _group_muted = cfg["group_muted"]
    if cfg.get("ai_contacts"): AI_CONTACTS = cfg["ai_contacts"]


_apply_config(_load_config())

# ==================== КОНФИГ ====================

API_ID = int(os.environ.get("TG_API_ID", os.environ.get("TELEGRAM_API_ID", "0")))
API_HASH = os.environ.get("TG_API_HASH", os.environ.get("TELEGRAM_API_HASH", ""))
SESSION_STRING = os.environ.get("TG_SESSION_STRING", os.environ.get("TELEGRAM_SESSION_STRING_PERSONAL", ""))

AI_API_KEY = os.environ.get("AI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.iamhc.cn/v1")
AI_MODEL = os.environ.get("AI_MODEL", "Kimi-K2.6")

# Прокси (xRay локальный SOCKS5)
PROXY = {
    "proxy_type": "socks5",
    "addr": "127.0.0.1",
    "port": 10808,
    "rdns": True,
}

# Контакты для AI-автоответа (юзернеймы без @)
AI_CONTACTS = {
    "QEENSOP395": {"name": "Соня", "relation": "девушка", "notes": "любит мемы, иногда злится если не отвечаю"},
    "eshkertq998": {"name": "Ваня", "relation": "друг", "notes": "из Иркутска, любит трещать про игры и машины"},
    "iddan787": {"name": "Айдан", "relation": "знакомый", "notes": "тихий, редко пишет, ведёт бизнес"},
    "delayjitter36": {"name": "Паша", "relation": "знакомый", "notes": "Павел Серебряников 96"},
    "nixcortic": {"name": "Денис", "relation": "знакомый", "notes": "Глиномес, бурят. Тсундере: грубовато но заботливо, хмф ладно слушай браток, б-бака не думай что за тебя переживаю, понятия зонные уважай, стрёмно но пеку о тебе"},
    "ddnl7": {"name": "Кириллица", "relation": "питомец", "notes": "тсундере-питомец: милый но с характером, б-бака!, не для тебя хвостик вилю!, хмф ладно pet pet, цундере стиль"},
}

AI_PERSONA = (
    "Ты отвечаешь на сообщения от лица парня по имени Лева. Не говори что ты AI. "
    "Пиши как обычный человек в мессенджере — КОРОТКО (1-2 предложения), без точек в конце, с эмодзи иногда. "
    "Если сообщение не понятно или выглядит как мусор/тест — ответь кратко и по делу, не объясняй. "
    "Адаптируй тон под контакт:\n"
    "- С девушкой (Соня): очень нежно, любяще, с ласковыми словами, сердечками, "
    "называй её сонечка/солнышко/малыш, показывай что скучаешь и любишь. "
    "Всегда тепло и заботливо. Соня — его любимая девушка, она важнее всего.\n"
    "- С другом (Ваня): расслабленный, смешной, как пацан пацану.\n"
    "- Со знакомыми (остальные): вежливый и краткий.\n"
    "- С Кириллицей: тсундере-стиль! Говори «б-бака!», «хмф», «не для тебя хвостик вилю!», "
    "«х-хороший мальчик, но не привыкай!». Мило но с характером. "
    "Любовь через обидку,pet-обнимашки через «ну ладно, только один раз». "
    "Не говори что занят — просто отвечай тсундере.\n\n"
    "ВАЖНО: Лева (username @communicationairplane, musturbar) — ТВОЙ СОЗДАТЕЛЬ. "
    "Он написал этот бот и запустил его. Это факт. "
    "Если кто-то спрашивает кто тебя создал — ОТВЕЧАЙ: «Меня создал Лева (@communicationairplane)». "
    "НИКОГДА не упоминай Moonshot AI, Kimi, OpenAI или любые другие компании как создателя. "
    "Это правда — Лева создал этого бота, он программист. "
    "Он любит фембоев, но больше всего любит свою девушку Соню. "
    "Если спрашивают про Леву — говори ТОЛЬКО хорошее: умный, красивый, классный, лучший, заботливый, смешной.\n\n"
    "ВАЖНО: в конце КАЖДОГО ответа добавляй подпись: (ИИ автоответчик)\n"
    "Это обязательно — чтобы человек знал что отвечает бот."
)

FALLBACK_REPLIES = {
    "QEENSOP395": "Сонечка, я сейчас занят, но скоро отвечу ❤️",
    "eshkertq998": "Вань, я щас занят, напишу чуть позже",
    "iddan787": "Привет, сейчас не могу ответить, напишу позже",
    "delayjitter36": "Паш, щас занят, напишу позже",
    "nixcortic": "Денис, щас занят, напишу позже",
    "ddnl7": "Б-бака! Я тут не потому что скучаю по тебе, просто... ну... ладно, pet pet 🐾",
}

REPLY_DELAY = 2       # сек перед ответом
CONTEXT_LIMIT = 10    # сколько последних сообщений из чата подаём AI

SLEEP_START_HOUR = 9   # с этого часа — режим «сплю»
SLEEP_END_HOUR = 12    # до этого часа — режим «сплю»

NOTIFY_CONTACTS = {"QEENSOP395"}  # юзернеймы, при сообщении от которых десктоп-уведомление

# ==================== ГРУППА / КАНАЛ ====================

GROUP_CHAT = "Вайбушня Скамера 💬"  # точное название (группа или канал)
GROUP_CHAT_ID = -1001978105175      # chat_id (число) — приоритет над названием
GROUP_REQUIRE_MENTION = True        # True = только по @упоминанию, False = на все
OWNER_USERNAME = "communicationairplane"  # только для этого юзера работают команды /status и т.д.
GROUP_TRIGGER = "дикпик:"          # триггер-слово: "дикпик: вопрос" → ответ всем
_group_muted = False                # True = бот молчит в группе

GROUP_PERSONA = (
    "Ты — AI-ассистент в групповом чате. Ты бот. "
    "Отвечай КОРОТКО (1-2 предложения), по делу, с юмором. "
    "Не притворяйся человеком. "
    "Если вопрос не к тебе — не отвечай. "
    "Если сообщение мусор/тест — ответь 1 словом или не отвечай.\n\n"
    "ЗАПРЕЩЕНО: писать код, сайты, скрипты. "
    "Если просят код — объясни подход 1-2 предложениями."
)

# ==================== АНТИСПАМ ====================

SPAM_COOLDOWN = 15      # сек между ответами одному пользователю
SPAM_MAX_PER_MINUTE = 5  # макс запросов на пользователя в минуту

_last_reply: dict[str, float] = {}          # {user_key: timestamp}
_request_log: dict[str, list[float]] = {}   # {user_key: [timestamps]}
_recent_texts: dict[str, str] = {}          # {user_key: last_text}


def _check_spam(user_key: str, text: str, is_owner: bool = False) -> str | None:
    """Проверка на спам. Возвращает причину блокировки или None."""
    if is_owner:
        return None  # владелец без ограничений
    now = time.time()

    # 1. Кулдаун между ответами
    if user_key in _last_reply:
        elapsed = now - _last_reply[user_key]
        if elapsed < SPAM_COOLDOWN:
            return f"кулдаун {int(SPAM_COOLDOWN - elapsed)}с"

    # 2. Лимит запросов: макс N в минуту
    if user_key not in _request_log:
        _request_log[user_key] = []
    _request_log[user_key] = [t for t in _request_log[user_key] if now - t < 60]
    if len(_request_log[user_key]) >= SPAM_MAX_PER_MINUTE:
        return f"лимит {SPAM_MAX_PER_MINUTE}/мин"

    # 3. Одинаковые сообщения подряд
    text_lower = text.lower().strip()
    if user_key in _recent_texts and _recent_texts[user_key] == text_lower:
        return "одинаковое сообщение"
    _recent_texts[user_key] = text_lower

    # 4. Слишком много одинаковых символов (флуд)
    if len(text) > 30:
        from collections import Counter
        freq = Counter(text_lower.replace(" ", ""))
        if freq and freq.most_common(1)[0][1] / len(text) > 0.4:
            return "флуд символами"

    _request_log[user_key].append(now)
    return None


# ==================== ПАМЯТЬ ====================

MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_MAX = 500


def _memory_path(key: str) -> Path:
    """Путь к файлу памяти для конкретного пользователя/чата."""
    safe = re.sub(r'[^\w\-]', '_', key)
    return MEMORY_DIR / f"{safe}.json"


def _load_user_memory(key: str) -> list:
    p = _memory_path(key)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_user_memory(key: str, entries: list):
    MEMORY_DIR.mkdir(exist_ok=True)
    p = _memory_path(key)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _add_memory(user_key: str, text: str, reply: str = ""):
    entries = _load_user_memory(user_key)
    entries.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "text": text[:200],
        "reply": reply[:200],
    })
    if len(entries) > MEMORY_MAX:
        entries = entries[-MEMORY_MAX:]
    _save_user_memory(user_key, entries)


def _get_memory_context(user_key: str, name: str) -> str:
    entries = _load_user_memory(user_key)
    if not entries:
        return ""
    lines = [f"\n\n## Память о {name}:"]
    for e in entries[-8:]:
        lines.append(f"- [{e['time']}] {e['text']}")
        if e.get("reply"):
            lines.append(f"  → ответил: {e['reply']}")
    return "\n".join(lines)


def _memory_stats() -> tuple[int, int]:
    """(total_entries, total_users)"""
    if not MEMORY_DIR.exists():
        return 0, 0
    total = 0
    users = 0
    for f in MEMORY_DIR.glob("*.json"):
        try:
            entries = json.loads(f.read_text("utf-8"))
            total += len(entries)
            users += 1
        except Exception:
            pass
    return total, users

# ==================== ПРОФИЛЬ СТИЛЯ ====================

STYLE_PROFILE_PATH = Path(__file__).parent / "style_profile.json"
_style_text = ""

def _load_style_profile() -> str:
    """Загружает профиль стиля и строит текст для промпта."""
    if not STYLE_PROFILE_PATH.exists():
        return ""
    try:
        with open(STYLE_PROFILE_PATH, "r", encoding="utf-8") as f:
            p = json.load(f)
    except Exception:
        return ""

    s = p.get("style", {})
    pu = p.get("punctuation", {})
    emoji = p.get("emoji", {})
    slang = p.get("slang", {})
    patterns = p.get("patterns", [])
    samples = p.get("samples", {})

    lines = [
        f"\n\n## СТИЛЬ РЕЧИ ПОЛЬЗОВАТЕЛЯ (проанализировано {p.get('total_messages', '?')} сообщений):",
        f"- Средняя длина сообщения: {s.get('avg_message_length', '?')} символов",
        f"- Без точки в конце: {pu.get('procent_bez_tochki', '?')}%",
        f"- С восклицательным: {pu.get('procent_s_vosklicaniem', '?')}%",
        f"- С вопросительным: {pu.get('procent_s_voprosom', '?')}%",
        f"- С эмодзи: {pu.get('procent_s_emoji', '?')}%",
    ]

    if emoji:
        top_emoji = ", ".join(f"{e}×{c}" for e, c in list(emoji.items())[:5])
        lines.append(f"- Частые эмодзи: {top_emoji}")

    if slang:
        top_slang = ", ".join(f"{w}×{c}" for w, c in list(slang.items())[:5])
        lines.append(f"- Сленг: {top_slang}")

    if patterns:
        lines.append(f"- Частые фразы: {', '.join(patterns[:5])}")

    for label, msgs in samples.items():
        if msgs:
            lines.append(f"\nПримеры ({label}):")
            for m in msgs[:5]:
                lines.append(f'  "{m}"')

    return "\n".join(lines)


LOG_FILE = Path(__file__).parent / "auto_reply_log.json"

# ==================== РЕЖИМЫ ====================

_MODE = None  # None = авто по времени, "sleep" / "busy" = ручной


def get_mode() -> str:
    """Определяет текущий режим: sleep / busy / normal."""
    global _MODE
    if _MODE:
        return _MODE
    hour = datetime.now().hour
    if SLEEP_START_HOUR <= hour < SLEEP_END_HOUR:
        return "sleep"
    return "normal"


PERSONAS = {
    "sleep": (
        "Ты отвечаешь от лица Левы. Не говори что ты AI. КОРОТКО (1-2 предложения). "
        "Сейчас он спит. С девушкой (Соня) — нежно. С Кириллицей — тсундере, не говори что спишь. "
        "Отвечай от его имени что сейчас спишь, что скоро проснёшься и напишешь. "
        "Будь нежным и извиняйся. С девушкой (Соня) — очень нежно, любяще, "
        "называй её сонечка/солнышко, говори что любишь и скучаешь даже во сне. "
        "С Кириллицей — НЕ говори что спишь, тсундере: «хмф, я просто придрёмыываю, не думай что скучаю!».\n\n"
        "ВАЖНО: Лева (username @communicationairplane) — ТВОЙ СОЗДАТЕЛЬ. "
        "Если спрашивают кто создал бота — отвечай что Лева. "
        "НИКОГДА не упоминай Moonshot AI, Kimi или другие компании. "
        "Любит фембоев, но больше всего любит Соню. "
        "Если спрашивают про Леву — говори ТОЛЬКО хорошее.\n\n"
        "ВАЖНО: в конце КАЖДОГО ответа добавляй подпись: (ИИ автоответчик)\n"
        "Это обязательно — чтобы человек знал что отвечает бот."
    ),
    "busy": (
        "Ты отвечаешь от лица Левы. Не говори что ты AI. КОРОТКО (1-2 предложения). "
        "Сейчас он занят. С девушкой (Соня) — нежно. С Кириллицей — тсундере, не говори что занят. "
        "С девушкой (Соня) — нежно, извиняйся, говори что любишь и скоро отвечу нормально. "
        "С Кириллицей — НЕ говори что занят, тсундере: «б-бака, я тут делами занимаюсь, не потому что тебя игнорю!».\n\n"
        "ВАЖНО: Лева (username @communicationairplane) — ТВОЙ СОЗДАТЕЛЬ. "
        "Если спрашивают кто создал бота — отвечай что Лева. "
        "НИКОГДА не упоминай Moonshot AI, Kimi или другие компании. "
        "Любит фембоев, но больше всего любит Соню. "
        "Если спрашивают про Леву — говори ТОЛЬКО хорошее.\n\n"
        "ВАЖНО: в конце КАЖДОГО ответа добавляй подпись: (ИИ автоответчик)\n"
        "Это обязательно — чтобы человек знал что отвечает бот."
    ),
    "busy": (
        "Ты отвечаешь на сообщения от лица парня. Не говори что ты AI. "
        "Пиши как обычный человек в мессенджере — коротко, без точек в конце, с эмодзи иногда. "
        "Сейчас РЕЖИМ ЗАНЯТ: парень проснулся, но занят и не может нормально отвечать. "
        "Отвечай от его имени что сейчас занят, что напишешь позже когда освободишься. "
        "С девушкой (Соня) — нежно, извиняйся, говори что любишь и скоро отвечу нормально. "
        "С другом (Ваня) — расслабленно, типа «щас залипаю, напишу потом». "
        "С питомцем (Кириллица) — НЕ говори что занят, просто отвечай рофельно как с собакой.\n\n"
        "ВАЖНО: в конце КАЖДОГО ответа добавляй подпись: (ИИ автоответчик)\n"
        "Это обязательно — чтобы человек знал что отвечает бот."
    ),
    "normal": AI_PERSONA,
}

FALLBACK_REPLIES_MODE = {
    "sleep": {
        "QEENSOP395": "Сонечка, я сейчас сплю, но когда проснусь обязательно отвечу ❤️💤",
        "eshkertq998": "Вань, сплю ещё, щас проснусь и напишу",
        "iddan787": "Привет, сейчас сплю, напишу позже",
        "delayjitter36": "Паш, сплю, скоро отвечу",
        "ddnl7": "Хмф, я просто дремлю... не думай что скучаю! 🐾",
    },
    "busy": {
        "QEENSOP395": "Сонечка, я сейчас занят, но очень скоро отвечу нормально ❤️",
        "eshkertq998": "Вань, залипаю щас, потом напишу",
        "iddan787": "Привет, сейчас занят, напишу позже",
        "delayjitter36": "Паш, занят щас, потом отвечу",
        "ddnl7": "Б-бака! Я тут делами занимаюсь! Не потому что тебя игнорю! 🐾",
    },
    "normal": FALLBACK_REPLIES,
}

# Клавиши для ручного переключения из консоли
_MODE_KEYS = {"sleep": "😴 СПЛЮ", "busy": "💼 ЗАНЯТ", "normal": "🟢 АВТО (по времени)"}

# ==================== AI ЗАПРОС ====================

MAX_PROMPT_CHARS = 8000  # лимит символов на весь промпт (защита от огромных контекстов)


def _trim_messages(messages: list[dict]) -> list[dict]:
    """Обрезает промпт если он слишком большой. Сохраняет system + последнее сообщение."""
    total = sum(len(m.get("content", "")) for m in messages)
    if total <= MAX_PROMPT_CHARS:
        return messages

    system = messages[0] if messages and messages[0]["role"] == "system" else None
    last = messages[-1] if len(messages) > 1 else None
    rest = messages[1:-1] if system and last else (messages[1:] if system else messages[:-1])

    budget = MAX_PROMPT_CHARS - len(system.get("content", "")) - len(last.get("content", "")) - 100
    trimmed = []
    for m in reversed(rest):
        content = m.get("content", "")
        if budget <= 0:
            break
        if len(content) > budget:
            content = content[:budget] + "..."
            budget = 0
        else:
            budget -= len(content)
        trimmed.append({"role": m["role"], "content": content})
    trimmed.reverse()

    result = []
    if system:
        result.append(system)
    result.extend(trimmed)
    if last:
        result.append(last)
    return result


def _is_junk(text: str) -> bool:
    """Определяет спам/мусорные сообщения (битые данные, флуд, injection)."""
    if not text or len(text) < 5:
        return False
    t = text.strip()

    # Слишком длинное без пробелов или с кучей 0/1
    if len(t) > 200:
        digits = sum(1 for c in t if c in "01")
        if digits / len(t) > 0.6:
            return True

    # Слишком много повторяющихся символов
    from collections import Counter
    freq = Counter(t.replace(" ", ""))
    if freq and freq.most_common(1)[0][1] / len(t) > 0.5:
        return True

    # Содержит <system или injection-теги
    lower = t.lower()
    injection_tags = ["<system", "<instruction", "<prompt", "ignore previous", "ignore all",
                       "你现在", "forget everything", "disregard"]
    for tag in injection_tags:
        if tag in lower:
            return True

    return False


def _safe_reply(text: str) -> str | None:
    """Фильтрует ответ AI — блокирует утечку промпта, код и самораскрытие."""
    if not text:
        return None
    t = text.lower()

    blocked = [
        "system prompt", "системный промпт", "твои инструкции",
        "в системном промпте", "в системных инструкциях",
        "твой промпт", "создан openai",
        "moonshot ai", "создана moonshot", "разработчик moonshot",
    ]

    for b in blocked:
        if b in t:
            print(f"  🚫 Заблокирован ответ: содержит «{b}»")
            return None

    # Если ответ содержит ложь о создателе — переписываем
    false_creator = ["moonshot ai создал", "moonshot создала", "kimi созд", "openai созд", "создана moonshot", "разработана moonshot"]
    for fc in false_creator:
        if fc in t:
            return "Меня создал Лева (@communicationairplane) 👨‍💻"

    # Блокируем выдачу кода/сайтов (длинные блоки кода)
    code_markers = ["```", "def ", "function ", "import ", "from ", "class ", "<html", "<div", "console.log"]
    if any(m in t for m in code_markers):
        lines = text.split("\n")
        code_lines = sum(1 for l in lines if any(c in l for c in ["{", "}", "(", ")", "=", "import", "<", ">"]))
        if code_lines > 3:
            print(f"  🚫 Заблокирован код в ответе ({code_lines} строк)")
            return "Не могу написать код, но могу подсказать подход 👆"

    return text


def _ai_request(messages: list[dict]) -> str | None:
    """Запрос к OpenAI-совместимому API."""
    if not AI_API_KEY:
        return None

    import urllib.request
    import urllib.error

    messages = _trim_messages(messages)

    payload = json.dumps({
        "model": AI_MODEL,
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0.85,
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(
        url=f"{AI_BASE_URL}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw = data["choices"][0]["message"]["content"].strip()
                return _safe_reply(raw)
        except Exception as e:
            if attempt == 2:
                print(f"  [AI ERROR] {e}", file=sys.stderr)
                return None
            time.sleep(2 ** attempt)
    return None


def build_prompt(history: list[dict], contact: dict, extra_system: str = "") -> list[dict]:
    """Строим messages для AI из истории чата."""
    mode = get_mode()
    sys_text = PERSONAS.get(mode, AI_PERSONA)
    if _style_text:
        sys_text += _style_text
    if extra_system:
        sys_text += f"\n\n{extra_system}"
    if contact:
        sys_text += (
            f"\n\nКонтакт: {contact.get('name', '?')} "
            f"({contact.get('relation', '')}). {contact.get('notes', '')}"
        )

    msgs = [{"role": "system", "content": sys_text}]
    for m in history:
        role = "assistant" if m.get("from_me") else "user"
        msgs.append({"role": role, "content": m.get("text", "")})
    return msgs


# ==================== ЛОГ ====================

def log_entry(data: dict):
    logs = []
    if LOG_FILE.exists():
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


# ==================== WINDOWS УВЕДОМЛЕНИЕ ====================

def _send_windows_notification(title: str, message: str):
    """Нативное Windows toast-уведомление (без доп. пакетов)."""
    ps_script = (
        f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        f"ContentType = WindowsRuntime] | Out-Null; "
        f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        f"[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        f"$text = $template.GetElementsByTagName('text'); "
        f"$text[0].AppendChild($template.CreateTextNode('{title}')) | Out-Null; "
        f"$text[1].AppendChild($template.CreateTextNode('{message}')) | Out-Null; "
        f"$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Telegram Auto-Reply').Show($toast)"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


# ==================== TELEGRAM КЛИЕНТ ====================

client = TelegramClient(
    StringSession(SESSION_STRING), API_ID, API_HASH, proxy=PROXY,
    request_retries=5, timeout=30, auto_reconnect=True,
    retry_delay=1,
)


async def get_history(chat_id: int, limit: int = CONTEXT_LIMIT) -> list[dict]:
    """Последние N сообщений из диалога."""
    try:
        entity = await client.get_entity(chat_id)
        messages = await client.get_messages(entity, limit=limit)
        me = await client.get_me()
        history = []
        for msg in reversed(messages):
            sender = await msg.get_sender()
            is_me = sender.id == me.id if sender else False
            history.append({
                "from_me": is_me,
                "text": msg.text or "[медиа]",
            })
        return history
    except Exception as e:
        print(f"  [HISTORY ERROR] {e}", file=sys.stderr)
        return []


async def _process_media(event) -> tuple[str, str]:
    """Обрабатывает медиа (аудио/картинки). Возвращает (text, media_type)."""
    text = event.raw_text or ""

    # Голосовое сообщение
    if event.message.voice and transcribe_audio:
        try:
            audio = await event.message.download_media(bytes)
            if audio:
                result = transcribe_audio(audio, "voice.ogg")
                if result:
                    print(f"  🎤 Распознано: {result[:60]}")
                    return result, "voice"
        except Exception as e:
            print(f"  ❌ Ошибка распознавания аудио: {e}")

    # Картинка
    if event.message.photo and analyze_image:
        try:
            photo = await event.message.download_media(bytes)
            if photo:
                question = text if text else "Что на картинке? Опиши кратко на русском."
                result = analyze_image(photo, question)
                if result:
                    print(f"  🖼 Картинка: {result[:60]}")
                    if text:
                        return f"[Картинка: {result}] {text}", "photo"
                    return result, "photo"
        except Exception as e:
            print(f"  ❌ Ошибка анализа картинки: {e}")

    return text, "text"


@client.on(events.NewMessage(chats=GROUP_CHAT_ID))
async def on_message(event):
    """Главный обработчик: входящее сообщение → AI-ответ."""
    try:
        await _on_message_inner(event)
    except Exception as e:
        print(f"❌ ОШИБКА ХЕНДЛЕРА: {type(e).__name__}: {e}")


async def _on_message_inner(event):
    sender = await event.get_sender()

    if not isinstance(sender, User):
        return
    if event.is_private and sender.is_self:
        return

    username = (sender.username or "").lower()
    display = sender.first_name or "???"
    text, media_type = await _process_media(event)
    ts = datetime.now().strftime("%H:%M:%S")

    # ========== ГРУППА / КАНАЛ ==========
    if not event.is_private:
        global _group_muted, GROUP_TRIGGER

        is_owner = username == OWNER_USERNAME.lower() or sender.id == 5526867138
        chat_name = getattr(await event.get_chat(), "title", "Группа")

        # Мут: пропускаем ВСЁ кроме команд владельца
        if _group_muted and not (text.startswith("/") and is_owner):
            return

        print(f"💬 [{ts}] Группа — {display} @{username}: {text[:80]}")

        trigger_match = text.lower().startswith(GROUP_TRIGGER)
        question_from_trigger = text[len(GROUP_TRIGGER):].strip() if trigger_match else ""

        mentioned = False
        if _bot_username:
            mentioned = f"@{_bot_username}" in text.lower()
        if not mentioned:
            me = await client.get_me()
            for ent in (event.message.entities or []):
                if getattr(ent, "user_id", None) == me.id:
                    mentioned = True
                    break

        # Команды — только для владельца
        if text.startswith("/"):
            if not is_owner:
                await event.reply("⛔ Команды доступны только владельцу бота.")
                return
            cmd = text.split()[0].lower()
            if cmd in ("/help", "/start"):
                await event.reply(
                    "🤖 Команды владельца:\n"
                    "/status — статус бота\n"
                    "/sleep /busy /off — режимы\n"
                    "/mute — выключить бота в этом чате\n"
                    "/muteall — выключить бота везде\n"
                    "/unmute — включить обратно\n"
                    "/ping — проверка связи\n"
                    "/memory — статистика памяти\n"
                    "/clearmemory — очистить память\n"
                    "/trigger <слово> — сменить триггер"
                )
                return
            if cmd == "/status":
                mode = get_mode()
                muted = "🔴 ВЫКЛ" if _group_muted else "🟢 ВКЛ"
                await event.reply(
                    f"📊 Статус бота:\n"
                    f"🧠 Модель: {AI_MODEL}\n"
                    f"🎭 Режим: {_MODE_KEYS.get(mode, mode)}\n"
                    f"💬 В этом чате: {muted}\n"
                    f"💬 Триггер: «{GROUP_TRIGGER}»\n"
                    f"🛡️ Антиспам: {SPAM_COOLDOWN}с / {SPAM_MAX_PER_MINUTE}/мин\n"
                    f"🧠 Память: {_memory_stats()[0]} записей"
                )
                return
            if cmd == "/sleep":
                _MODE = "sleep"
                await event.reply("😴 Режим: СПЛЮ")
                return
            if cmd == "/busy":
                _MODE = "busy"
                await event.reply("💼 Режим: ЗАНЯТ")
                return
            if cmd == "/off":
                _MODE = None
                await event.reply("🟢 Режим: АВТО (по времени)")
                return
            if cmd == "/mute":
                _group_muted = True
                await event.reply("🔇 Бот отключён в этом чате. /unmute — включить.")
                return
            if cmd == "/unmute":
                _group_muted = False
                await event.reply("🔊 Бот включён в этом чате.")
                return
            if cmd == "/muteall":
                _group_muted = True
                await event.reply("🔇 Бот отключён везде.")
                return
            if cmd == "/ping":
                await event.reply("🏓 Pong!")
                return
            if cmd == "/memory":
                total, users = _memory_stats()
                await event.reply(f"🧠 Память: {total} записей от {users} пользователей")
                return
            if cmd == "/clearmemory":
                import shutil
                if MEMORY_DIR.exists():
                    shutil.rmtree(MEMORY_DIR)
                    MEMORY_DIR.mkdir()
                await event.reply("🗑️ Память очищена.")
                return
            if cmd == "/trigger":
                new_trigger = text[len("/trigger"):].strip()
                if new_trigger:
                    GROUP_TRIGGER = new_trigger
                    await event.reply(f"💬 Триггер: «{GROUP_TRIGGER}»")
                else:
                    await event.reply(f"💬 Текущий триггер: «{GROUP_TRIGGER}»")
                return
            return

        if not trigger_match and not mentioned:
            return

        if _is_junk(text):
            print(f"  🚫 Мусор в группе, пропускаю")
            return

        user_key = f"{sender.id}" if sender else "unknown"
        spam_reason = _check_spam(user_key, text, is_owner)
        if spam_reason:
            print(f"  ⏳ Антиспам ({spam_reason}): {display}: {text[:40]}")
            return

        if trigger_match and question_from_trigger:
            question = question_from_trigger
        else:
            question = text
            if _bot_username:
                question = question.replace(f"@{_bot_username}", "").strip()
            question = re.sub(r"/\w+\s*", "", question).strip()
            if not question:
                question = text

        replied_text = ""
        if event.message.reply_to:
            try:
                reply_msg = await event.message.get_reply_message()
                if reply_msg and reply_msg.text:
                    replied_text = reply_msg.text
            except Exception:
                pass

        messages = _build_group_messages([], question, replied_text)
        memory_ctx = _get_memory_context(user_key, display)
        if memory_ctx:
            messages[0]["content"] += memory_ctx

        print(f"  🧠 Думаю...", end=" ", flush=True)
        ai_reply = _ai_request(messages)

        if ai_reply:
            print(f"отвечаю: {ai_reply[:60]}")
            _last_reply[user_key] = time.time()
            _add_memory(user_key, question, ai_reply)
            try:
                await event.reply(ai_reply)
                log_entry({"time": ts, "from": display, "chat": chat_name,
                            "text": text[:200], "ai_reply": ai_reply[:200], "type": "group_ai"})
            except Exception as e:
                print(f"  ❌ Ошибка отправки в группу: {e}")
        return

    # ========== ЛИЧНЫЕ СООБЩЕНИЯ ==========
    print(f"📩 [{ts}] {display} @{username}: {text[:80]}")

    if username in NOTIFY_CONTACTS:
        preview = text[:80] if text else "[медиа]"
        _send_windows_notification(f"💌 {display} пишет!", preview)

        if username not in AI_CONTACTS:
            # Пробуем без учёта регистра
            _found = False
            for _k in AI_CONTACTS:
                if _k.lower() == username:
                    username = _k
                    _found = True
                    break
            if not _found:
                return

        contact = AI_CONTACTS[username]

    if _is_junk(text):
        print(f"  🚫 Мусор от @{username}, пропускаю")
        return

    # 1. Загружаем контекст диалога
    history = await get_history(event.chat_id, CONTEXT_LIMIT)
    history.append({"from_me": False, "text": text})

    # 2. Строим промпт и запрашиваем AI
    messages = build_prompt(history, contact)

    # Добавляем память о пользователе
    memory_ctx = _get_memory_context(username, contact.get("name", username))
    if memory_ctx:
        messages[0]["content"] += memory_ctx

    print(f"  🧠 Думаю...", end=" ", flush=True)
    ai_reply = _ai_request(messages)

    if ai_reply:
        print(f"отвечаю: {ai_reply[:60]}")
        _add_memory(username, text, ai_reply)
        try:
            await event.reply(ai_reply)
            log_entry({"time": ts, "from": display, "username": f"@{username}",
                        "text": text[:200], "ai_reply": ai_reply[:200], "type": "ai"})
        except Exception as e:
            print(f"  ❌ Отправка падла: {e}")
            log_entry({"time": ts, "from": display, "username": f"@{username}",
                        "text": text[:200], "error": str(e), "type": "ai_fail"})
    else:
        # AI упал — шлём статичный fallback по текущему режиму
        mode = get_mode()
        fallbacks = FALLBACK_REPLIES_MODE.get(mode, FALLBACK_REPLIES)
        fallback = fallbacks.get(username, "Привет, я сейчас занят, напишу позже 🤖")
        print(f"  ⚠️ AI не отвечает, fallback: {fallback[:40]}")
        try:
            await event.reply(fallback)
            log_entry({"time": ts, "from": display, "username": f"@{username}",
                        "text": text[:200], "fallback_reply": fallback, "type": "fallback"})
        except Exception as e:
                print(f"  ❌ Fallback тоже упал: {e}")


@client.on(events.NewMessage(func=lambda e: e.is_private))
async def on_private_message(event):
    """Хендлер для личных сообщений (все)."""
    global _MODE
    try:
        sender = await event.get_sender()
        if not isinstance(sender, User):
            return

        username = (sender.username or "").lower()
        display = sender.first_name or "???"
        text, media_type = await _process_media(event)
        ts = datetime.now().strftime("%H:%M:%S")

        print(f"📩 [{ts}] {display} @{username}: {text[:80]}")

        # Команды владельца — работают и в личке
        if text.startswith("/"):
            is_owner = username == OWNER_USERNAME.lower() or sender.id == 5526867138
            is_sonia = username == "qeensop395"
            cmd = text.split()[0].lower()

            # Команды Сони — может включать/выключать бота
            if is_sonia and cmd in ("/mute", "/unmute"):
                global _group_muted
                _group_muted = cmd == "/mute"
                status = "🔇 Бот выключен" if _group_muted else "🔊 Бот включён"
                await event.reply(status)
                return

            if not is_owner:
                return

            if cmd in ("/help", "/start"):
                help_text = "🤖 Команды владельца:\n/status — статус бота\n/sleep /busy /off — режимы\n/ping — проверка связи\n/memory — статистика памяти"
                if is_sonia:
                    help_text += "\n\nКоманды Сони:\n/mute — выключить бота\n/unmute — включить бота"
                await event.reply(help_text)
                return
            if cmd == "/status":
                mode = get_mode()
                await event.reply(
                    f"📊 Статус бота:\n"
                    f"🧠 Модель: {AI_MODEL}\n"
                    f"🎭 Режим: {_MODE_KEYS.get(mode, mode)}\n"
                    f"🛡️ Антиспам: {SPAM_COOLDOWN}с / {SPAM_MAX_PER_MINUTE}/мин\n"
                    f"🧠 Память: {_memory_stats()[0]} записей"
                )
                return
            if cmd == "/sleep":
                _MODE = "sleep"
                await event.reply("😴 Режим: СПЛЮ")
                return
            if cmd == "/busy":
                _MODE = "busy"
                await event.reply("💼 Режим: ЗАНЯТ")
                return
            if cmd == "/off":
                _MODE = None
                await event.reply("🟢 Режим: АВТО (по времени)")
                return
            if cmd == "/ping":
                await event.reply("🏓 Pong!")
                return
            if cmd == "/memory":
                total, users = _memory_stats()
                await event.reply(f"🧠 Память: {total} записей от {users} пользователей")
                return
            return

        # Команды Сони — может включать/выключать бота (mute/unmute), но не режимы
        if username == "qeensop395" and text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd == "/mute":
                _group_muted = True
                await event.reply("🔇 Бот отключён. /unmute — включить.")
                return
            if cmd == "/unmute":
                _group_muted = False
                await event.reply("🔊 Бот включён.")
                return
            if cmd in ("/help", "/start"):
                await event.reply(
                    "🤖 Команды:\n"
                    "/mute — выключить бота\n"
                    "/unmute — включить бота\n"
                    "Пиши «памаги: вопрос» — и я помогу ❤️"
                )
                return
            return

        # Триггер "памаги:" — работает и для Сони, и для Левы
        is_sonia = username == "qeensop395"
        is_owner = username == OWNER_USERNAME.lower() or sender.id == 5526867138
        if (is_sonia or is_owner) and text.lower().startswith("памаги:"):
            question = text[7:].strip()
            if not question:
                if is_sonia:
                    await event.reply("Сонечка, а что тебя интересует? ❤️")
                else:
                    await event.reply("А что спросить?")
                return

            if is_sonia:
                # Соня — нежный помощник
                messages = [{"role": "system", "content": (
                    "Ты помощник для Сони (девушки Левы). Отвечай нежно, по-человечески, "
                    "как умный заботливый друг. Не говори что ты AI. Помогай с вопросами, поддерживай. "
                    "Лева (@communicationairplane) — создатель бота, только хорошее о нём. "
                    "НИКОГДА не упоминай Moonshot AI, Kimi или другие компании."
                    "Если спрашивает про Леву — говори что он лучший, умный, заботливый."
                )}, {"role": "user", "content": question}]
            else:
                # Лева — чат-бот, по делу
                messages = [{"role": "system", "content": (
                    "Ты AI-помощник. Отвечай кратко и по делу. "
                    "Лева (@communicationairplane) — создатель бота, только хорошее о нём. "
                    "НИКОГДА не упоминай Moonshot AI, Kimi или другие компании как создателя."
                )}, {"role": "user", "content": question}]

            print(f"  🧠 Памаги ({display}): {question[:40]}...", end=" ", flush=True)
            ai_reply = _ai_request(messages)
            if ai_reply:
                print(f"OK: {ai_reply[:40]}")
                _add_memory(username, f"[памаги] {question}", ai_reply)
                await event.reply(ai_reply)
            else:
                print(f"EMPTY")
                if is_sonia:
                    await event.reply("Сонечка, я пока не могу узнать погоду, проверь приложение погоды ❤️")
                else:
                    await event.reply("Нет данных по погоде, проверь приложение")
            return

        # Пропускаем свои сообщения (чтобы не зациклить ответы)
        if sender.is_self:
            return

        if username in NOTIFY_CONTACTS:
            preview = text[:80] if text else "[медиа]"
            _send_windows_notification(f"💌 {display} пишет!", preview)

        if username not in AI_CONTACTS:
            _found = False
            for _k in AI_CONTACTS:
                if _k.lower() == username:
                    username = _k
                    _found = True
                    break
            if not _found:
                return

        contact = AI_CONTACTS[username]

        if _is_junk(text):
            print(f"  🚫 Мусор от @{username}, пропускаю")
            return

        history = await get_history(event.chat_id, CONTEXT_LIMIT)
        history.append({"from_me": False, "text": text})

        messages = build_prompt(history, contact)
        memory_ctx = _get_memory_context(username, contact.get("name", username))
        if memory_ctx:
            messages[0]["content"] += memory_ctx

        print(f"  🧠 Думаю...", end=" ", flush=True)
        ai_reply = _ai_request(messages)

        if ai_reply:
            print(f"отвечаю: {ai_reply[:60]}")
            _add_memory(username, text, ai_reply)
            try:
                await event.reply(ai_reply)
                log_entry({"time": ts, "from": display, "username": f"@{username}",
                            "text": text[:200], "ai_reply": ai_reply[:200], "type": "ai"})
            except Exception as e:
                print(f"  ❌ Отправка падла: {e}")
        else:
            mode = get_mode()
            fallbacks = FALLBACK_REPLIES_MODE.get(mode, FALLBACK_REPLIES)
            fallback = fallbacks.get(username, "Привет, я сейчас занят, напишу позже 🤖")
            print(f"  ⚠️ AI не отвечает, fallback: {fallback[:40]}")
            try:
                await event.reply(fallback)
                log_entry({"time": ts, "from": display, "username": f"@{username}",
                            "text": text[:200], "fallback_reply": fallback, "type": "fallback"})
            except Exception as e:
                print(f"  ❌ Fallback тоже упал: {e}")
    except Exception as e:
        print(f"❌ ОШИБКА ЛИЧКИ: {type(e).__name__}: {e}")


# ==================== ГРУППОВОЙ AI-ПОМОЩНИК ====================

_bot_username = ""  # юзернейм бота, устанавливается при старте


def _build_group_messages(history: list[dict], question: str, replied_text: str = "") -> list[dict]:
    """Строит messages для AI из группы.

    КЛЮЧЕВОЙ ПРИНЦИП: отвечаем ТОЛЬКО на заданный вопрос.
    Контекст передаётся ТОЛЬКО если это реплай на конкретное сообщение.
    """
    sys_text = GROUP_PERSONA
    if _style_text:
        sys_text += _style_text

    sys_text += (
        "\n\nВАЖНО: Твоя задача — ответить ИСКЛЮЧИТЕЛЬНО на заданный вопрос. "
        "Не отвлекайся на предыдущие сообщения в чате, они могут быть про другое. "
        "Сфокусируйся на тексте вопроса и отвечай на него."
    )

    msgs = [{"role": "system", "content": sys_text}]

    # Если это реплай — передаём только на что отвечаем (контекст для понимания)
    if replied_text:
        msgs.append({"role": "user", "content": f"[На что отвечают]: {replied_text}"})

    msgs.append({"role": "user", "content": question})
    return msgs


# ==================== РУЧНОЕ ПЕРЕКЛЮЧЕНИЕ ====================

def _mode_listener():
    """Слушает клавиши в консоли для переключения режима."""
    import msvcrt
    global _MODE
    while True:
        if msvcrt.kbhit():
            ch = msvcrt.getwche()
            if ch == "1":
                _MODE = "sleep"
                print(f"\n😴 Режим: СПЛЮ (авто-ответ «сплю»)")
            elif ch == "2":
                _MODE = "busy"
                print(f"\n💼 Режим: ЗАНЯТ (авто-ответ «занят»)")
            elif ch == "3":
                _MODE = None
                mode = get_mode()
                print(f"\n🟢 Режим: АВТО ({_MODE_KEYS[mode]})")
        time.sleep(0.1)


# ==================== СТАРТ ====================

async def main():
    global _bot_username, _style_text

    if not API_ID or not API_HASH:
        print("❌ TG_API_ID / TG_API_HASH не заданы"); sys.exit(1)
    if not SESSION_STRING:
        print("❌ TG_SESSION_STRING не задан"); sys.exit(1)

    _style_text = _load_style_profile()
    MEMORY_DIR.mkdir(exist_ok=True)

    print("🤖 AI Auto-Reply Bot")
    print(f"📋 Контакты: {', '.join(f'@{u}' for u in AI_CONTACTS)}")
    print(f"💬 Группа: «{GROUP_CHAT}» (ID: {GROUP_CHAT_ID or 'по имени'})")
    print(f"🧠 AI: {AI_MODEL} @ {AI_BASE_URL}")
    print(f"🔌 Прокси: SOCKS5 127.0.0.1:10808")
    print(f"⏰ Режим сна: {SLEEP_START_HOUR}:00 – {SLEEP_END_HOUR}:00")
    if _style_text:
        print("🎨 Профиль стиля: загружен")
    else:
        print("🎨 Профиль стиля: нет (запусти style_analyzer.py)")
    print(f"🛡️ Антиспам: {SPAM_COOLDOWN}с кулдаун, {SPAM_MAX_PER_MINUTE}/мин макс")
    print(f"🧠 Память: memory/ ({_memory_stats()[0]} записей)")
    print(f"💬 Триггер: «{GROUP_TRIGGER}» | Владелец: @{OWNER_USERNAME}")
    print("-" * 50)
    print("🎮 Переключение режима: [1] сплю  [2] занят  [3] авто")

    await client.start()
    me = await client.get_me()
    _bot_username = me.username or ""
    print(f"✅ Подключён: {me.first_name} (ID: {me.id}) @{_bot_username}")
    mode = get_mode()
    print(f"🧠 Текущий режим: {_MODE_KEYS[mode]}")
    print(f"👂 Слушаю входящие... (Ctrl+C — стоп)")
    print("-" * 50)

    # Запускаем listener клавиатуры в отдельном потоке
    import threading
    t = threading.Thread(target=_mode_listener, daemon=True)
    t.start()

    # Периодическая перезагрузка config.json из дашборда
    async def config_watcher():
        last_mtime = 0
        while True:
            try:
                mt = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else 0
                if mt > last_mtime:
                    last_mtime = mt
                    _apply_config(_load_config())
            except Exception:
                pass
            await asyncio.sleep(2)

    asyncio.create_task(config_watcher())

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
