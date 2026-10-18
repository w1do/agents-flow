"""Регистрация webhook в Telegram: публичный адрес https и список типов обновлений.

Команда `harness-server telegram set-webhook` вызывает эти функции. Секрет проверки передаётся
в setWebhook и сверяется в api/deps.py (D-29). Адрес с учётными данными отвергается: он попал бы
в логи и ответы.
"""

from typing import Final
from urllib.parse import urlsplit

from harness_server.adapters.telegram.protocol import TelegramClient

WEBHOOK_PATH: Final = "/telegram/webhook"
# Только то, что обрабатывает бот: правки сообщений, стикеры и прочее Telegram не присылает.
ALLOWED_UPDATES: Final = ("message", "callback_query")


def webhook_url(public_url: str | None) -> str:
    """Полный адрес webhook из публичного адреса сервера. ValueError — если адрес не подходит."""
    if not public_url:
        raise ValueError("не задан")
    parts = urlsplit(public_url)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("нужен адрес https://")
    if "@" in parts.netloc:
        raise ValueError("адрес не должен содержать учётные данные")
    # Query и fragment к адресу webhook не относятся: путь к нему дописывается к базовому адресу.
    if parts.query or parts.fragment:
        raise ValueError("адрес не должен содержать query или fragment")
    return public_url.rstrip("/") + WEBHOOK_PATH


async def register_webhook(telegram: TelegramClient, url: str, secret_token: str) -> None:
    """Регистрирует webhook с секретом и ALLOWED_UPDATES. Ошибки Telegram — TelegramError."""
    await telegram.set_webhook(url, secret_token=secret_token, allowed_updates=ALLOWED_UPDATES)
