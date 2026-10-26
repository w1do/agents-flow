"""Живая проверка Telegram Bot API: отправка и правка сообщения настоящим ботом.

Не входит в `./tools/harness check` (маркер `live`, addopts = -m 'not live'). Запуск вручную:
`uv run pytest -m live apps/server/tests/test_telegram_live.py`. Нужны LIVE_TELEGRAM_BOT_TOKEN и
LIVE_TELEGRAM_CHAT_ID (чат, где бот может писать). Без них тест пропускается. Токен не печатается.
"""

import os

import httpx
import pytest
from harness_server.adapters.telegram import HttpxTelegramClient

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]

_TOKEN_ENV = "LIVE_TELEGRAM_BOT_TOKEN"
_CHAT_ENV = "LIVE_TELEGRAM_CHAT_ID"


async def test_live_send_and_edit_message() -> None:
    token = os.environ.get(_TOKEN_ENV)
    chat_id_raw = os.environ.get(_CHAT_ENV)
    if not token or not chat_id_raw:
        pytest.skip(f"нужны переменные {_TOKEN_ENV} и {_CHAT_ENV}")
    chat_id = int(chat_id_raw)

    # Прокси берём из отдельной live-переменной: conftest очищает HTTPS_PROXY для всех тестов.
    proxy = os.environ.get("LIVE_HTTPS_PROXY") or None
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), proxy=proxy) as http:
        client = HttpxTelegramClient(token, http)
        message_id = await client.send_message(chat_id, "harness live: отправка")
        await client.edit_message_text(chat_id, message_id, "harness live: правка")
        # Повторная правка тем же текстом: Telegram отвечает «message is not modified», это успех.
        await client.edit_message_text(chat_id, message_id, "harness live: правка")
