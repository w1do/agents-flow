"""Маршрутизация текста владельца в приёме: класс, кнопки, уточнение, запасной путь (mvp-05).

Сервисы открывают свои сессии, поэтому тесты идут на committed_session_factory (реальные коммиты) и
фейках адаптеров. Состояние проверяется в БД и во фейке, без ожиданий по времени.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from harness_server.adapters.polza import FakeRouter, RouterError
from harness_server.adapters.stt import FakeSpeechToText
from harness_server.adapters.telegram import FakeTelegramClient, InlineKeyboard
from harness_server.db.ids import uuid7
from harness_server.db.models import Routing, Sandbox, Task
from harness_server.services.context import BotContext
from harness_server.services.intake import process_recorded, record_incoming
from harness_server.services.tasks import list_tasks
from harness_server.telegram.parse import dedup_key, parse_update
from harness_server.telegram.render import (
    TEXT_HELP,
    TEXT_NO_OPEN_TASKS,
    build_clarify_callback,
    clarify_closed_text,
    clarify_text,
    short_title,
)
from harness_shared.routing import CommandClass, RoutingDecisionKind
from harness_shared.tasks import TaskKind, TaskSource, TaskStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Значение из conftest.make_bot_context: секрет, который не должен уйти в маршрутизатор.
SECRET = "test-webhook-secret-0123456789abcdef"
COMMAND = "сделай авторизацию по email"


async def _record_and_process(
    factory: async_sessionmaker[AsyncSession], ctx: BotContext, raw: dict[str, Any]
) -> None:
    """Записывает апдейт и сразу обрабатывает его, как фоновая задача webhook."""
    incoming = parse_update(raw)
    assert incoming is not None
    async with factory() as session:
        assert await record_incoming(session, incoming) is True
    kind, external_id = dedup_key(incoming)
    await process_recorded(ctx, kind, external_id)


def _text(
    telegram_update: Callable[[str], dict[str, Any]], text: str, update_id: int
) -> dict[str, Any]:
    raw = telegram_update("text_message")
    raw["update_id"] = update_id
    raw["message"]["text"] = text
    return raw


def _press(
    telegram_update: Callable[[str], dict[str, Any]],
    data: str,
    *,
    callback_id: str = "4242000000000000001",
    update_id: int = 10003,
    message_id: int = 100,
) -> dict[str, Any]:
    raw = telegram_update("callback_query")
    raw["update_id"] = update_id
    raw["callback_query"]["id"] = callback_id
    raw["callback_query"]["data"] = data
    raw["callback_query"]["message"]["message_id"] = message_id
    return raw


def _ws_press(
    telegram_update: Callable[[str], dict[str, Any]],
    task_id: UUID,
    workspace: str,
    *,
    callback_id: str = "4242000000000000001",
    update_id: int = 10003,
) -> dict[str, Any]:
    return _press(
        telegram_update,
        f"ws:{task_id.hex}:{workspace}",
        callback_id=callback_id,
        update_id=update_id,
    )


def _button_texts(keyboard: InlineKeyboard | None) -> list[str]:
    assert keyboard is not None
    return [button.text for row in keyboard.rows for button in row]


async def _tasks(factory: async_sessionmaker[AsyncSession]) -> list[Task]:
    async with factory() as session:
        return await list_tasks(session)


async def _routings(factory: async_sessionmaker[AsyncSession]) -> list[Routing]:
    async with factory() as session:
        result = await session.execute(select(Routing).order_by(Routing.created_at, Routing.id))
        return list(result.scalars().all())


async def _clarify_routing(factory: async_sessionmaker[AsyncSession]) -> Routing:
    """Единственное решение уточнения: отдаётся тестам, которые ждут вопрос с кнопками."""
    rows = [r for r in await _routings(factory) if r.decision is RoutingDecisionKind.CLARIFY]
    assert len(rows) == 1
    return rows[0]


async def test_work_command_creates_task_with_ranked_buttons(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter(
        routing_content("work", 0.9, [("shop", 0.3), ("demo", 0.8)], title="авторизация")
    )
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)

    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, COMMAND, 10001)
    )

    tasks = await _tasks(committed_session_factory)
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.CHOOSING
    assert _button_texts(fake.sent[0].reply_markup) == ["Демо-проект", "Магазин"]
    [routing] = await _routings(committed_session_factory)
    assert routing.decision is RoutingDecisionKind.AUTO
    assert routing.command_class is CommandClass.WORK
    assert routing.task_id == tasks[0].id
    assert routing.options == [{"id": "demo", "score": 0.8}, {"id": "shop", "score": 0.3}]


async def test_ghost_workspace_not_shown(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter(routing_content("work", 0.9, [("ghost", 0.9), ("demo", 0.5)]))
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)

    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, COMMAND, 10001)
    )

    assert _button_texts(fake.sent[0].reply_markup) == ["Демо-проект"]


async def test_work_without_known_candidates_shows_all_workspaces(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter(routing_content("work", 0.9, [("ghost", 0.9)]))
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)

    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, COMMAND, 10001)
    )

    assert _button_texts(fake.sent[0].reply_markup) == ["Демо-проект", "Магазин"]


async def test_unknown_command_replies_help(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter(routing_content("unknown", 0.9))
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)

    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, "какая погода", 10001)
    )

    assert fake.sent[0].text == TEXT_HELP
    assert await _tasks(committed_session_factory) == []
    [routing] = await _routings(committed_session_factory)
    assert routing.task_id is None


async def test_low_confidence_asks_clarification(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter(routing_content("work", 0.4, [("demo", 0.8)]))
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)

    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, COMMAND, 10001)
    )

    assert await _tasks(committed_session_factory) == []
    assert len(fake.sent) == 1
    assert fake.sent[0].text == clarify_text(short_title(COMMAND))
    keyboard = fake.sent[0].reply_markup
    assert keyboard is not None
    [row] = keyboard.rows
    assert [b.text for b in row] == ["Сделать задачу", "Показать статус"]
    routing = await _clarify_routing(committed_session_factory)
    assert row[0].callback_data == build_clarify_callback(routing.id, "w")
    assert row[1].callback_data == build_clarify_callback(routing.id, "s")
    assert routing.source_text == COMMAND


async def test_clarify_do_task_creates_task(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter(routing_content("work", 0.4, [("demo", 0.8)]))
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)
    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, COMMAND, 10001)
    )
    routing = await _clarify_routing(committed_session_factory)

    data = build_clarify_callback(routing.id, "w")
    await _record_and_process(
        committed_session_factory,
        ctx,
        _press(telegram_update, data, callback_id="4242000000000000007", update_id=10002),
    )

    [task] = await _tasks(committed_session_factory)
    assert task.status == TaskStatus.CHOOSING
    async with committed_session_factory() as session:
        stored = await session.get(Routing, routing.id)
    assert stored is not None
    assert stored.task_id == task.id
    assert stored.resolved_at is not None
    assert stored.source_text is None
    assert fake.callback_answers[-1] == ("4242000000000000007", None)
    assert fake.edits[-1].text == clarify_closed_text(short_title(COMMAND), "w")
    assert fake.edits[-1].reply_markup is None
    # Вторая отправка — карточка с кнопками кандидатов решения.
    assert _button_texts(fake.sent[-1].reply_markup) == ["Демо-проект"]


async def test_clarify_show_status_replies_report(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter(routing_content("work", 0.4, [("demo", 0.8)]))
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)
    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, COMMAND, 10001)
    )
    routing = await _clarify_routing(committed_session_factory)

    await _record_and_process(
        committed_session_factory,
        ctx,
        _press(telegram_update, build_clarify_callback(routing.id, "s"), update_id=10002),
    )

    assert await _tasks(committed_session_factory) == []
    assert fake.sent[-1].text == TEXT_NO_OPEN_TASKS


async def test_clarify_repeat_press_answers_already(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter(routing_content("work", 0.4, [("demo", 0.8)]))
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)
    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, COMMAND, 10001)
    )
    routing = await _clarify_routing(committed_session_factory)
    data = build_clarify_callback(routing.id, "w")

    await _record_and_process(
        committed_session_factory,
        ctx,
        _press(telegram_update, data, callback_id="4242000000000000008", update_id=10002),
    )
    await _record_and_process(
        committed_session_factory,
        ctx,
        _press(telegram_update, data, callback_id="4242000000000000009", update_id=10003),
    )

    assert len(await _tasks(committed_session_factory)) == 1
    assert fake.callback_answers[-1] == ("4242000000000000009", "уже выбрано")


async def test_clarify_garbage_callback(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=FakeRouter("{}"))

    await _record_and_process(committed_session_factory, ctx, _press(telegram_update, "rt:zzz:w"))

    assert fake.callback_answers == [("4242000000000000001", "кнопка устарела")]


async def test_clarify_unknown_routing(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=FakeRouter("{}"))

    await _record_and_process(
        committed_session_factory,
        ctx,
        _press(telegram_update, f"rt:{uuid7().hex}:w"),
    )

    assert fake.callback_answers == [("4242000000000000001", "кнопка устарела")]
    assert await _tasks(committed_session_factory) == []


async def test_router_unavailable_shows_all_workspaces(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter(error=RouterError("timeout"))
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)

    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, COMMAND, 10001)
    )

    [task] = await _tasks(committed_session_factory)
    assert task.status == TaskStatus.CHOOSING
    assert _button_texts(fake.sent[0].reply_markup) == ["Демо-проект", "Магазин"]
    [routing] = await _routings(committed_session_factory)
    assert routing.decision is RoutingDecisionKind.FALLBACK
    assert routing.error == "timeout"

    await _record_and_process(
        committed_session_factory,
        ctx,
        _ws_press(telegram_update, task.id, "demo", update_id=10002),
    )

    [task] = await _tasks(committed_session_factory)
    assert task.status == TaskStatus.PLANNING
    [routing] = await _routings(committed_session_factory)
    assert routing.chosen_workspace_id == "demo"


async def test_invalid_router_response_shows_all_workspaces(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    router = FakeRouter("не json")
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)

    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, COMMAND, 10001)
    )

    assert _button_texts(fake.sent[0].reply_markup) == ["Демо-проект", "Магазин"]
    [routing] = await _routings(committed_session_factory)
    assert routing.raw_response == "не json"
    assert routing.error == "invalid_decision"


async def test_status_command_lists_open_tasks(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    async with committed_session_factory() as session:
        for text, status, workspace in (
            ("добавь экспорт", TaskStatus.PLANNING, "demo"),
            ("сделай витрину", TaskStatus.CHOOSING, None),
            ("завершённая задача", TaskStatus.MERGED, "demo"),
            ("выброшенная задача", TaskStatus.TRASH, "shop"),
        ):
            session.add(
                Task(
                    kind=TaskKind.PLAN,
                    text=text,
                    status=status,
                    source=TaskSource.TELEGRAM,
                    workspace_id=workspace,
                )
            )
        await session.commit()
    fake = FakeTelegramClient()
    router = FakeRouter(routing_content("status", 0.9))
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)

    await _record_and_process(
        committed_session_factory, ctx, _text(telegram_update, "какие задачи открыты", 10001)
    )

    assert len(fake.sent) == 1
    text = fake.sent[0].text
    assert "Демо-проект:" in text
    assert "Без проекта:" in text
    assert "завершённая задача" not in text
    assert "выброшенная задача" not in text
    assert len(await _tasks(committed_session_factory)) == 4
    async with committed_session_factory() as session:
        sandboxes = await session.execute(select(func.count()).select_from(Sandbox))
    assert sandboxes.scalar_one() == 0
    assert len(router.calls) == 1


async def test_voice_command_is_routed(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    audio = b"OggS-voice-bytes"
    fake = FakeTelegramClient(files={"VOICE_FILE_1": audio})
    stt = FakeSpeechToText("какие задачи открыты")
    router = FakeRouter(routing_content("status", 0.9))
    ctx = make_bot_context(committed_session_factory, telegram=fake, stt=stt, router=router)

    await _record_and_process(committed_session_factory, ctx, telegram_update("voice_message"))

    assert len(stt.calls) == 1
    assert len(router.calls) == 1
    assert fake.sent[0].text == TEXT_NO_OPEN_TASKS


async def test_secret_not_sent_to_router(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    routing_content: Callable[..., str],
) -> None:
    router = FakeRouter(routing_content("unknown", 0.9))
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake, router=router)

    await _record_and_process(
        committed_session_factory,
        ctx,
        _text(telegram_update, f"почини доступ {SECRET}", 10001),
    )

    sent_text = router.calls[0][1]
    assert "[REDACTED]" in sent_text
    assert SECRET not in sent_text
