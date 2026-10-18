"""Сообщения владельцу: одна карточка на задачу, этапы дописываются, редакция и ошибки Telegram."""

from collections.abc import Callable

import pytest
from harness_server.adapters.telegram import FakeTelegramClient, TelegramError
from harness_server.db.models import Task
from harness_server.db.models import TelegramMessage as Card
from harness_server.services.context import BotContext
from harness_server.services.notify import append_stage, send_task_card
from harness_server.services.tasks import change_status, create_task
from harness_shared.tasks import TaskEventSource, TaskKind, TaskSource, TaskStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = "test-webhook-secret-0123456789abcdef"
CARD_LINE = "Задача [добавь экспорт в CSV] (выберите проект)"
TASK_TEXT = "добавь экспорт в CSV"


async def _choosing_task(factory: async_sessionmaker[AsyncSession], text: str = TASK_TEXT) -> Task:
    async with factory() as session:
        task = await create_task(
            session,
            kind=TaskKind.PLAN,
            text=text,
            source=TaskSource.TELEGRAM,
            known_workspace_ids=("demo", "shop"),
        )
        return await change_status(
            session, task.id, TaskStatus.CHOOSING, source=TaskEventSource.TELEGRAM
        )


async def _card(factory: async_sessionmaker[AsyncSession], task_id: object) -> Card | None:
    async with factory() as session:
        result = await session.execute(select(Card).where(Card.task_id == task_id))
        return result.scalar_one_or_none()


async def test_two_stages_single_message(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    fake = FakeTelegramClient()
    ctx: BotContext = make_bot_context(committed_session_factory, telegram=fake)
    task = await _choosing_task(committed_session_factory)

    await send_task_card(ctx, task)
    await append_stage(ctx, task.id, "начата")
    await append_stage(ctx, task.id, "готова, MR создан")

    assert len(fake.sent) == 1
    assert len(fake.edits) == 2
    final = fake.texts[fake.sent[0].message_id]
    assert final.splitlines()[-2:] == [
        "Задача [добавь экспорт в CSV] (начата)",
        "Задача [добавь экспорт в CSV] (готова, MR создан)",
    ]
    assert "Задача [добавь экспорт в CSV] (выберите проект)" in final
    # Правка без клавиатуры: Bot API убирает кнопки.
    assert fake.edits[-1].reply_markup is None


async def test_not_editable_falls_back_to_new_message(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _choosing_task(committed_session_factory)
    await send_task_card(ctx, task)
    old_message_id = fake.sent[0].message_id
    fake.not_editable.add(old_message_id)

    await append_stage(ctx, task.id, "начата")

    assert len(fake.sent) == 2
    card = await _card(committed_session_factory, task.id)
    assert card is not None
    assert card.message_id == fake.sent[1].message_id
    assert card.message_id != old_message_id
    assert len(card.lines) == 2
    assert "Задача [добавь экспорт в CSV] (начата)" in fake.sent[1].text


async def test_append_stage_without_card_sends_message(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _choosing_task(committed_session_factory)

    await append_stage(ctx, task.id, "начата")

    assert len(fake.sent) == 1
    assert fake.sent[0].reply_markup is None
    card = await _card(committed_session_factory, task.id)
    assert card is not None
    assert card.lines == ["Задача [добавь экспорт в CSV] (начата)"]


async def test_append_stage_redacts_secrets(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _choosing_task(committed_session_factory, text=f"добавь экспорт {SECRET}")

    await append_stage(ctx, task.id, "начата")

    assert SECRET not in fake.sent[0].text
    assert "[REDACTED]" in fake.sent[0].text


async def test_other_telegram_error_keeps_lines(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _choosing_task(committed_session_factory)
    await send_task_card(ctx, task)
    fake.fail_with = TelegramError("editMessageText", 500, "Internal Server Error")

    await append_stage(ctx, task.id, "начата")

    card = await _card(committed_session_factory, task.id)
    assert card is not None
    assert len(card.lines) == 2
    assert fake.edits == []


async def test_send_task_card_is_idempotent(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _choosing_task(committed_session_factory)

    await send_task_card(ctx, task)
    await send_task_card(ctx, task)

    assert len(fake.sent) == 1
