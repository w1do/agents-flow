"""Webhook Telegram: принимает апдейт, записывает его и отвечает сразу, не дожидаясь обработки.

Тонкий вход (CLAUDE.md, §3): секрет, разбор апдейта, фильтр владельца и постановка в фон.
STT, создание задачи и карточка идут в services/intake.process_recorded уже после ответа Telegram.
"""

from typing import Final

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from harness_server.api.deps import BotContextDep, SessionDep, require_webhook_secret
from harness_server.services.intake import process_recorded, record_incoming
from harness_server.telegram.parse import dedup_key, parse_update

_OK: Final = {"ok": True}

# Секрет проверяется до тела запроса: без верного заголовка апдейт даже не разбирается.
router = APIRouter(tags=["telegram"], dependencies=[Depends(require_webhook_secret)])


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    bot: BotContextDep,
) -> dict[str, bool]:
    """Чужие чаты и неподдерживаемые апдейты получают 200 и ничего не сохраняют и не отправляют."""
    try:
        raw: object = await request.json()
    except ValueError:
        return _OK
    incoming = parse_update(raw)
    if incoming is None or incoming.chat_id != bot.owner_chat_id:
        return _OK
    if await record_incoming(session, incoming):
        kind, external_id = dedup_key(incoming)
        background_tasks.add_task(process_recorded, bot, kind, external_id)
    return _OK
