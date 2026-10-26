"""Восстановление Telegram живёт на сервере, где доступны БД и адаптеры бота."""

import asyncio
import logging

from harness_server.services.context import BotContext
from harness_server.services.intake import recover_pending

logger = logging.getLogger(__name__)


async def recover(bot: BotContext) -> None:
    """Восстановление в фоне; ошибки БД не прерывают следующие попытки."""
    try:
        await recover_pending(bot)
    except Exception as exc:
        logger.warning("telegram recovery failed type=%s", type(exc).__name__)


async def recovery_loop(bot: BotContext) -> None:
    """Проверяет апдейты сразу и затем раз в минуту, не задерживая старт сервера."""
    while True:
        await recover(bot)
        await asyncio.sleep(60)
