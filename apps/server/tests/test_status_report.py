"""Ответ на запрос состояния: открытые статусы, группы по проекту, секреты (D-34)."""

from collections.abc import Callable

import pytest
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.db.models import Task
from harness_server.services.context import BotContext
from harness_server.services.status_report import OPEN_STATUSES, build_status_report
from harness_server.telegram.render import TEXT_NO_OPEN_TASKS
from harness_shared.tasks import TaskKind, TaskSource, TaskStatus
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Значение из conftest.make_bot_context: попадает в secret_values и не должно уйти в отчёт.
SECRET = "test-webhook-secret-0123456789abcdef"


def test_open_statuses_exclude_merged_and_trash() -> None:
    assert TaskStatus.MERGED not in OPEN_STATUSES
    assert TaskStatus.TRASH not in OPEN_STATUSES
    assert TaskStatus.PLANNING in OPEN_STATUSES


async def _add(
    factory: async_sessionmaker[AsyncSession],
    text: str,
    status: TaskStatus,
    workspace_id: str | None,
) -> None:
    async with factory() as session:
        session.add(
            Task(
                kind=TaskKind.PLAN,
                text=text,
                status=status,
                source=TaskSource.TELEGRAM,
                workspace_id=workspace_id,
            )
        )
        await session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_report_groups_in_config_order(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    await _add(committed_session_factory, "сделай витрину", TaskStatus.PLANNING, "shop")
    await _add(committed_session_factory, "добавь экспорт в CSV", TaskStatus.PLANNING, "demo")
    await _add(committed_session_factory, "старая задача", TaskStatus.ACTIVE, "legacy")
    await _add(committed_session_factory, "сделай авторизацию", TaskStatus.CHOOSING, None)
    await _add(committed_session_factory, "уже готово", TaskStatus.MERGED, "demo")
    ctx = make_bot_context(committed_session_factory, telegram=FakeTelegramClient())

    text = await build_status_report(ctx)

    assert text.index("Демо-проект:") < text.index("Магазин:")
    assert text.index("Магазин:") < text.index("legacy:")
    assert text.index("legacy:") < text.index("Без проекта:")
    assert "• добавь экспорт в CSV — planning" in text
    assert "• сделай авторизацию — choosing" in text
    assert "уже готово" not in text
    assert text.startswith("Открытые задачи: 4")


@pytest.mark.asyncio(loop_scope="session")
async def test_report_no_open_tasks(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    await _add(committed_session_factory, "только завершённая", TaskStatus.TRASH, "demo")
    ctx = make_bot_context(committed_session_factory, telegram=FakeTelegramClient())

    assert await build_status_report(ctx) == TEXT_NO_OPEN_TASKS


@pytest.mark.asyncio(loop_scope="session")
async def test_report_redacts_secrets(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    await _add(committed_session_factory, f"почини доступ {SECRET}", TaskStatus.NEW, "demo")
    ctx = make_bot_context(committed_session_factory, telegram=FakeTelegramClient())

    text = await build_status_report(ctx)

    assert SECRET not in text
    assert "[REDACTED]" in text
