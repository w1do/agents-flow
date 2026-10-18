"""Приём сообщений владельца: голос, ошибки STT, выбор workspace кнопкой, повторная обработка.

Сервисы открывают свои сессии, поэтому тесты идут на committed_session_factory (реальные коммиты) и
фейках
адаптеров. Состояние проверяется в БД и во фейке, без ожиданий по времени.
"""

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from harness_server.adapters.stt import FakeSpeechToText, SttError
from harness_server.adapters.telegram import FakeTelegramClient, TelegramError
from harness_server.db.ids import uuid7
from harness_server.db.models import Task, TelegramMessage, TelegramUpdate
from harness_server.services.context import BotContext
from harness_server.services.intake import process_recorded, record_incoming
from harness_server.services.tasks import list_task_events, list_tasks
from harness_server.telegram.parse import dedup_key, parse_update
from harness_shared.tasks import TaskSource, TaskStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

STT_ERROR_TEXT = "не удалось распознать, пришлите текстом"
CARD_LINE = "Задача [создай страницу контактов] (выберите проект)"


async def _record_and_process(
    factory: async_sessionmaker[AsyncSession], ctx: BotContext, raw: dict[str, Any]
) -> None:
    """Записывает апдейт в telegram_updates и сразу обрабатывает его, как фоновая задача webhook."""
    incoming = parse_update(raw)
    assert incoming is not None
    async with factory() as session:
        assert await record_incoming(session, incoming) is True
    kind, external_id = dedup_key(incoming)
    await process_recorded(ctx, kind, external_id)


async def _tasks(factory: async_sessionmaker[AsyncSession]) -> list[Task]:
    async with factory() as session:
        return await list_tasks(session)


async def _count_cards(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        result = await session.execute(select(func.count()).select_from(TelegramMessage))
        return int(result.scalar_one())


async def test_voice_creates_task_with_transcript(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    audio = b"OggS-voice-bytes"
    fake = FakeTelegramClient(files={"VOICE_FILE_1": audio})
    stt = FakeSpeechToText("создай страницу контактов")
    ctx = make_bot_context(committed_session_factory, telegram=fake, stt=stt)

    await _record_and_process(committed_session_factory, ctx, telegram_update("voice_message"))

    tasks = await _tasks(committed_session_factory)
    assert len(tasks) == 1
    assert tasks[0].text == "создай страницу контактов"
    assert tasks[0].status == TaskStatus.CHOOSING
    assert tasks[0].source == TaskSource.TELEGRAM
    assert stt.calls == [(len(audio), "voice.ogg", "audio/ogg")]
    assert fake.sent[0].text.splitlines()[0] == "создай страницу контактов"
    assert fake.sent[0].text.splitlines()[-1] == CARD_LINE


async def test_stt_error_replies_and_creates_no_task(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient(files={"VOICE_FILE_1": b"OggS"})
    stt = FakeSpeechToText(error=SttError("stt http 500"))
    ctx = make_bot_context(committed_session_factory, telegram=fake, stt=stt)

    await _record_and_process(committed_session_factory, ctx, telegram_update("voice_message"))

    assert await _tasks(committed_session_factory) == []
    assert len(fake.sent) == 1
    assert fake.sent[0].text == STT_ERROR_TEXT
    assert fake.sent[0].reply_markup is None


async def test_stt_empty_text_replies(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient(files={"VOICE_FILE_1": b"OggS"})
    ctx = make_bot_context(committed_session_factory, telegram=fake, stt=FakeSpeechToText("   "))

    await _record_and_process(committed_session_factory, ctx, telegram_update("voice_message"))

    assert await _tasks(committed_session_factory) == []
    assert fake.sent[0].text == STT_ERROR_TEXT


async def test_stt_not_configured_replies(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient(files={"VOICE_FILE_1": b"OggS"})
    ctx = make_bot_context(committed_session_factory, telegram=fake, stt=None)

    await _record_and_process(committed_session_factory, ctx, telegram_update("voice_message"))

    assert await _tasks(committed_session_factory) == []
    assert fake.sent[0].text == STT_ERROR_TEXT


async def test_voice_over_limit_replies(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    # file_size в фикстуре — 2048 байт, лимит — 1024: файл не скачивается и в STT не уходит.
    fake = FakeTelegramClient(files={"VOICE_FILE_1": b"x" * 2048})
    stt = FakeSpeechToText("не должно вызываться")
    ctx = make_bot_context(committed_session_factory, telegram=fake, stt=stt, voice_max_bytes=1024)

    await _record_and_process(committed_session_factory, ctx, telegram_update("voice_message"))

    assert stt.calls == []
    assert await _tasks(committed_session_factory) == []
    assert fake.sent[0].text == STT_ERROR_TEXT


async def _text_task(
    factory: async_sessionmaker[AsyncSession],
    ctx: BotContext,
    telegram_update: Callable[[str], dict[str, Any]],
    raw: dict[str, Any] | None = None,
) -> Task:
    await _record_and_process(factory, ctx, raw or telegram_update("text_message"))
    tasks = await _tasks(factory)
    assert len(tasks) == 1
    return tasks[0]


def _press(
    telegram_update: Callable[[str], dict[str, Any]],
    task_id: UUID,
    workspace: str,
    *,
    callback_id: str = "4242000000000000001",
    update_id: int = 10003,
) -> dict[str, Any]:
    raw = telegram_update("callback_query")
    raw["update_id"] = update_id
    raw["callback_query"]["id"] = callback_id
    raw["callback_query"]["data"] = f"ws:{task_id.hex}:{workspace}"
    return raw


async def test_choose_workspace_sets_planning(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _text_task(committed_session_factory, ctx, telegram_update)

    await _record_and_process(
        committed_session_factory, ctx, _press(telegram_update, task.id, "shop")
    )

    async with committed_session_factory() as session:
        stored = (await list_tasks(session))[0]
        events = await list_task_events(session, task.id)
    assert stored.status == TaskStatus.PLANNING
    assert stored.workspace_id == "shop"
    assert events[-1].status == TaskStatus.PLANNING
    assert fake.callback_answers == [("4242000000000000001", None)]
    assert fake.edits[-1].reply_markup is None
    assert fake.texts[fake.sent[0].message_id].splitlines()[-1] == (
        "Задача [добавь экспорт в CSV] (проект «Магазин», планирование)"
    )


async def test_repeat_press_after_choice(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _text_task(committed_session_factory, ctx, telegram_update)
    await _record_and_process(
        committed_session_factory, ctx, _press(telegram_update, task.id, "shop")
    )

    await _record_and_process(
        committed_session_factory,
        ctx,
        _press(
            telegram_update,
            task.id,
            "demo",
            callback_id="4242000000000000002",
            update_id=10007,
        ),
    )

    async with committed_session_factory() as session:
        stored = (await list_tasks(session))[0]
        events = await list_task_events(session, task.id)
    assert stored.workspace_id == "shop"
    assert [e.status for e in events].count(TaskStatus.PLANNING) == 1
    assert fake.callback_answers[-1] == ("4242000000000000002", "проект уже выбран")


async def test_unknown_workspace_button(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _text_task(committed_session_factory, ctx, telegram_update)

    await _record_and_process(
        committed_session_factory, ctx, _press(telegram_update, task.id, "nope")
    )

    assert fake.callback_answers == [("4242000000000000001", "проект не найден")]
    assert (await _tasks(committed_session_factory))[0].status == TaskStatus.CHOOSING


async def test_garbage_callback(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    raw = telegram_update("callback_query")
    raw["callback_query"]["data"] = "garbage"

    await _record_and_process(committed_session_factory, ctx, raw)

    assert fake.callback_answers == [("4242000000000000001", "кнопка устарела")]


async def test_missing_task_button(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)

    await _record_and_process(
        committed_session_factory, ctx, _press(telegram_update, uuid7(), "demo")
    )

    assert fake.callback_answers == [("4242000000000000001", "задача не найдена")]


async def test_process_recorded_twice_creates_one_task(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    raw = telegram_update("text_message")
    await _record_and_process(committed_session_factory, ctx, raw)

    await process_recorded(ctx, "update", "10001")

    assert len(await _tasks(committed_session_factory)) == 1
    assert await _count_cards(committed_session_factory) == 1
    assert len(fake.sent) == 1


async def test_card_send_failure_keeps_task_without_duplicate(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    fake.fail_with = TelegramError("sendMessage", 500, "Internal Server Error")
    ctx = make_bot_context(committed_session_factory, telegram=fake)

    await _record_and_process(committed_session_factory, ctx, telegram_update("text_message"))

    tasks = await _tasks(committed_session_factory)
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.CHOOSING
    assert await _count_cards(committed_session_factory) == 0

    fake.fail_with = None
    await process_recorded(ctx, "update", "10001")

    assert len(await _tasks(committed_session_factory)) == 1
    async with committed_session_factory() as session:
        row = await session.get(TelegramUpdate, ("update", "10001"))
    assert row is not None
    assert row.processed_at is not None


# Точное значение секрета из фикстуры make_bot_context (conftest.py: VALID_WEBHOOK_SECRET).
TEST_SECRET = "test-webhook-secret-0123456789abcdef"


async def test_secret_in_text_not_stored(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    # Секрет вводят в чат по ошибке: в tasks.text он не должен попасть (S4).
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    raw = telegram_update("text_message")
    raw["message"]["text"] = f"почини вебхук {TEST_SECRET} сегодня"

    task = await _text_task(committed_session_factory, ctx, telegram_update, raw=raw)

    assert TEST_SECRET not in task.text
    assert TEST_SECRET not in fake.sent[0].text


async def test_secret_in_voice_transcript_not_stored(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient(files={"VOICE_FILE_1": b"OggS"})
    stt = FakeSpeechToText(f"ключ {TEST_SECRET} в конфиге")
    ctx = make_bot_context(committed_session_factory, telegram=fake, stt=stt)

    await _record_and_process(committed_session_factory, ctx, telegram_update("voice_message"))

    tasks = await _tasks(committed_session_factory)
    assert len(tasks) == 1
    assert TEST_SECRET not in tasks[0].text


async def test_long_token_at_text_start_not_partly_leaked(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    # Токен GitLab длиннее 40 символов: если бы усечение шло раньше redact, в заголовке
    # остался бы фрагмент, который шаблоны уже не узнают (S4).
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    raw = telegram_update("text_message")
    raw["message"]["text"] = "glpat-" + "a" * 40 + " поправь деплой"

    await _record_and_process(committed_session_factory, ctx, raw)

    assert "aaaaaaaa" not in fake.sent[0].text
    assert "glpat-" not in fake.sent[0].text
    assert fake.sent[0].text.splitlines()[-1].startswith("Задача [[REDACTED]")


async def test_concurrent_process_creates_one_task(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    # Два параллельных process_recorded на одном ключе: блокировка строки оставляет одну задачу.
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    incoming = parse_update(telegram_update("text_message"))
    assert incoming is not None
    async with committed_session_factory() as session:
        assert await record_incoming(session, incoming) is True
    kind, external_id = dedup_key(incoming)

    await asyncio.gather(
        process_recorded(ctx, kind, external_id),
        process_recorded(ctx, kind, external_id),
    )

    assert len(await _tasks(committed_session_factory)) == 1
    assert await _count_cards(committed_session_factory) == 1
    assert len(fake.sent) == 1
