#!/usr/bin/env python3
"""Модуль для распознавания аудио и анализа картинок."""
import base64
import json
import os
import urllib.request
import urllib.error
from pathlib import Path


def _get_api():
    env = Path.home() / "AppData/Local/hermes/.env"
    if env.exists():
        for line in env.read_text("utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

    key = os.environ.get("AI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    base = os.environ.get("AI_BASE_URL", "https://api.iamhc.cn/v1")
    return key, base


_whisper_available = None  # None = не проверено, True/False


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str | None:
    """Аудио-транскрипция недоступна на текущем API."""
    return None


def analyze_image(image_bytes: bytes, question: str = "Что на картинке? Опиши кратко.") -> str | None:
    """Анализ картинки через Kimi Vision API."""
    key, base = _get_api()
    if not key:
        return None

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif image_bytes[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"GIF8":
        mime = "image/gif"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": question},
            ],
        }
    ]

    payload = json.dumps({
        "model": "Kimi-K2.6",
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0.85,
    }).encode("utf-8")

    req = urllib.request.Request(
        base + "/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"].strip()
        except Exception:
            if attempt == 2:
                return None
            import time
            time.sleep(1)
    return None


if __name__ == "__main__":
    print("Media module loaded OK")
    print(f"API key: {'SET' if _get_api()[0] else 'NOT SET'}")
