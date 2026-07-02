# Telegram Auto-Reply Bot

Автоответчик для личного Telegram-аккаунта.

## Что делает
- 📩 Уведомляет в консоль о всех входящих личных сообщениях
- 🤖 Автоматически отвечает указанным контактам от твоего имени
- 📝 Логирует все сообщения в `auto_reply_log.json`

## Установка

```bash
pip install telethon
# или
uv pip install telethon
```

## Первый запуск

1. Получи API ID и API Hash на https://my.telegram.org
2. Установи переменные окружения:

```bash
# Linux/Mac
export TG_API_ID=12345678
export TG_API_HASH=your_hash_here
export TG_PHONE=+79991234567

# Windows CMD
set TG_API_ID=12345678
set TG_API_HASH=your_hash_here
set TG_PHONE=+79991234567
```

3. Запусти скрипт:

```bash
python auto_reply.py
```

4. При первом запуске Telegram пришлёт код — введи его в консоль

## Как настроить контакты

Отредактируй в `auto_reply.py`:

- `AUTO_REPLY_CONTACTS` — список юзернеймов для автоответа
- `CUSTOM_REPLIES` — уникальные ответы для каждого контакта
- `DEFAULT_REPLY` — ответ по умолчанию
- `REPLY_DELAY` — задержка в секундах перед ответом

## Остановка

`Ctrl+C` в консоли
