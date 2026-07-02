#!/usr/bin/env python3
"""
Анализатор стиля сообщений.
Вытягивает твои отправленные сообщения из Telegram,
анализирует манеру речи и сохраняет профиль в style_profile.json.
"""

import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

# Подгружаем .env
def _load_env(path: str):
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

_load_env(Path.home() / "AppData" / "Local" / "hermes" / ".env")

API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION_STRING = os.environ.get("TG_SESSION_STRING", os.environ.get("TELEGRAM_SESSION_STRING_PERSONAL", ""))

PROXY = {
    "proxy_type": "socks5",
    "addr": "127.0.0.1",
    "port": 10808,
    "rdns": True,
}

PROFILE_FILE = Path(__file__).parent / "style_profile.json"

EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "]+",
    flags=re.UNICODE,
)

SLANG_PATTERNS = [
    "хаха", "хех", "хд", "хз", "кек", "лол", "лмао", "гг", "ггг",
    "капец", "блин", "че", "чё", "какого", "лолка", "норм", "нормас",
    "круто", "прикинь", "короче", "типа", "пиздец", "блять", "бля",
    "нахуй", "йо", "йоу", "бро", "братан", "чувак", "чел",
    "сук", "самый", "вау", "ого", "офигеть", "поганый",
    "кайф", "дроп", "скинь", "свап", "вайб", "вайбушня",
    "нах", "кекв", "лолкек", "пжл", "пж", "нп", "нп",
]


def _count_emoji(texts: list[str]) -> dict:
    counter = Counter()
    for t in texts:
        for e in EMOJI_RE.findall(t):
            counter[e] += 1
    return dict(counter.most_common(15))


def _count_slang(texts: list[str]) -> dict:
    joined = " ".join(texts).lower()
    found = {}
    for pat in SLANG_PATTERNS:
        count = len(re.findall(rf"\b{re.escape(pat)}\b", joined))
        if count > 0:
            found[pat] = count
    return dict(sorted(found.items(), key=lambda x: -x[1])[:15])


def _avg_len(texts: list[str]) -> float:
    if not texts:
        return 0
    return round(sum(len(t) for t in texts) / len(texts), 1)


def _punctuation_habits(texts: list[str]) -> dict:
    total = len(texts)
    if total == 0:
        return {}
    no_period = sum(1 for t in texts if not t.rstrip().endswith("."))
    excl = sum(1 for t in texts if "!" in t)
    quest = sum(1 for t in texts if "?" in t)
    ellipsis = sum(1 for t in texts if "..." in t)
    emoji_ratio = sum(1 for t in texts if EMOJI_RE.search(t)) / total
    return {
        "procent_bez_tochki": round(no_period / total * 100),
        "procent_s_voprosom": round(quest / total * 100),
        "procent_s_vosklicaniem": round(excl / total * 100),
        "procent_s_mnogoточиem": round(ellipsis / total * 100),
        "procent_s_emoji": round(emoji_ratio * 100),
    }


def _extract_patterns(texts: list[str]) -> list[str]:
    """Находит часто повторяющиеся фразы."""
    bigrams = Counter()
    for t in texts:
        words = t.lower().split()
        for i in range(len(words) - 1):
            bg = f"{words[i]} {words[i+1]}"
            bigrams[bg] += 1
    return [f'"{ph}" (×{c})' for ph, c in bigrams.most_common(10) if c >= 3]


async def analyze(client: TelegramClient, limit_per_chat: int = 500):
    me = await client.get_me()
    print(f"📊 Анализирую стиль: {me.first_name} (ID: {me.id})")

    all_texts = []
    chats = await client.get_dialogs(limit=30)

    for dialog in chats:
        if dialog.is_group or dialog.is_channel:
            continue
        try:
            messages = await client.get_messages(dialog.entity, limit=limit_per_chat)
            for msg in messages:
                if msg.sender_id == me.id and msg.text:
                    all_texts.append(msg.text)
        except Exception:
            continue

    print(f"📝 Собрано {len(all_texts)} сообщений из {len(chats)} чатов")

    if len(all_texts) < 10:
        print("❌ Слишком мало сообщений для анализа")
        return None

    lengths = [len(t) for t in all_texts]
    words = " ".join(all_texts).split()
    word_count = Counter(w.lower() for w in words if len(w) > 2)

    profile = {
        "me_id": me.id,
        "me_name": me.first_name,
        "total_messages": len(all_texts),
        "style": {
            "avg_message_length": _avg_len(all_texts),
            "median_length": sorted(lengths)[len(lengths) // 2],
            "short_ratio": round(sum(1 for l in lengths if l < 20) / len(lengths) * 100),
            "long_ratio": round(sum(1 for l in lengths if l > 100) / len(lengths) * 100),
        },
        "punctuation": _punctuation_habits(all_texts),
        "emoji": _count_emoji(all_texts),
        "slang": _count_slang(all_texts),
        "top_words": dict(word_count.most_common(30)),
        "patterns": _extract_patterns(all_texts),
        "samples": {
            "short": [t for t in all_texts if len(t) < 15][:10],
            "medium": [t for t in all_texts if 15 <= len(t) <= 60][:10],
            "long": [t for t in all_texts if len(t) > 60][:10],
        },
    }

    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print(f"✅ Профиль сохранён: {PROFILE_FILE}")
    _print_summary(profile)
    return profile


def _print_summary(p: dict):
    s = p["style"]
    pu = p["punctuation"]
    print("\n" + "=" * 50)
    print(f"📊 СТИЛЬ: {p['me_name']}")
    print(f"  Сообщений проанализировано: {p['total_messages']}")
    print(f"  Средняя длина: {s['avg_message_length']} символов")
    print(f"  Коротких (<20): {s['short_ratio']}% | Длинных (>100): {s['long_ratio']}%")
    print(f"  Без точки в конце: {pu.get('procent_bez_tochki', '?')}%")
    print(f"  С восклицательным: {pu.get('procent_s_vosklicaniem', '?')}%")
    print(f"  С вопросительным: {pu.get('procent_s_voprosom', '?')}%")
    print(f"  С эмодзи: {pu.get('procent_s_emoji', '?')}%")
    if p["emoji"]:
        top3 = list(p["emoji"].items())[:5]
        print(f"  Топ эмодзи: {', '.join(f'{e}×{c}' for e, c in top3)}")
    if p["slang"]:
        top3 = list(p["slang"].items())[:5]
        print(f"  Сленг: {', '.join(f'{w}×{c}' for w, c in top3)}")
    if p["patterns"]:
        print(f"  Частые фразы: {', '.join(p['patterns'][:5])}")
    print("=" * 50)


async def main():
    if not API_ID or not API_HASH:
        print("❌ TG_API_ID / TG_API_HASH не заданы")
        sys.exit(1)
    if not SESSION_STRING:
        print("❌ TG_SESSION_STRING не задан")
        sys.exit(1)

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH, proxy=PROXY)
    await client.start()
    await analyze(client)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
