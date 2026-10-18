"""Восстановление после рестарта (D-27): брошенные апдейты и карточки досылаются при старте."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.db.models import Task, TelegramMessage, TelegramUpdate
from harness_server.services import intake
from harness_server.services.context import BotContext
from harness_server.services.intake import PAYLOAD_TTL, recover_pending
from harness_server.services.tasks import change_status, create_task, list_tasks
from harness_server.telegram.parse import dedup_key, dump_incoming, parse_update
from harness_shared.tasks import TaskEventSource, TaskKind, TaskSource, TaskStatus
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

OLD = timedelta(minutes=2)


async def _insert_update(
    factory: async_sessionmaker[AsyncSession],
    raw: dict[str, Any],
    *,
    received_at: datetime,
    keep_payload: bool = True,
    processed_at: datetime | None = None,
) -> tuple[str, str]:
    """Кладёт строку telegram_updates с явным received_at, как после приёма webhook до рестарта."""
    incoming = parse_update(raw)
    assert incoming is not None
    kind, external_id = dedup_key(incoming)
    payload = dump_incoming(incoming) if keep_payload else None
    async with factory() as session:
        await session.execute(
            postgresql.insert(TelegramUpdate).values(
                kind=kind,
                external_id=external_id,
                payload=payload,
                received_at=received_at,
                processed_at=processed_at,
            )
        )
        await session.commit()
    return kind, external_id


async def _update_row(
    factory: async_sessionmaker[AsyncSession], kind: str, external_id: str
) -> TelegramUpdate:
    async with factory() as session:
        row = await session.get(TelegramUpdate, (kind, external_id))
    assert row is not None
    return row


async def _task_count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return len(await list_tasks(session))


async def _sql_null_payload_count(factory: async_sessionmaker[AsyncSession]) -> int:
    """Обработанные строки, где payload — SQL NULL, а не JSON 'null' (D-27)."""
    async with factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(TelegramUpdate)
            .where(TelegramUpdate.payload.is_(None), TelegramUpdate.processed_at.is_not(None))
        )
        return int(result.scalar_one())


async def test_recover_processes_stale_update(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    kind, external_id = await _insert_update(
        committed_session_factory,
        telegram_update("text_message"),
        received_at=datetime.now(UTC) - OLD,
    )

    processed = await recover_pending(ctx)

    assert processed == 1
    row = await _update_row(committed_session_factory, kind, external_id)
    assert row.processed_at is not None
    assert row.payload is None
    assert await _sql_null_payload_count(committed_session_factory) == 1
    async with committed_session_factory() as session:
        tasks = await list_tasks(session)
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.CHOOSING
    assert len(fake.sent) == 1


async def test_recover_skips_fresh_update(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    kind, external_id = await _insert_update(
        committed_session_factory,
        telegram_update("text_message"),
        received_at=datetime.now(UTC),
    )

    processed = await recover_pending(ctx)

    assert processed == 0
    row = await _update_row(committed_session_factory, kind, external_id)
    assert row.processed_at is None
    assert await _task_count(committed_session_factory) == 0
    assert fake.sent == []


async def test_recover_skips_processed_update(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    await _insert_update(
        committed_session_factory,
        telegram_update("text_message"),
        received_at=datetime.now(UTC) - OLD,
        keep_payload=False,
        processed_at=datetime.now(UTC) - OLD,
    )

    processed = await recover_pending(ctx)

    assert processed == 0
    assert await _task_count(committed_session_factory) == 0
    assert fake.sent == []


async def test_recover_marks_legacy_row_without_payload(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    kind, external_id = await _insert_update(
        committed_session_factory,
        telegram_update("text_message"),
        received_at=datetime.now(UTC) - OLD,
        keep_payload=False,
    )

    await recover_pending(ctx)

    row = await _update_row(committed_session_factory, kind, external_id)
    assert row.processed_at is not None
    assert await _task_count(committed_session_factory) == 0


async def _aged_task(factory: async_sessionmaker[AsyncSession], *, to_choosing: bool) -> Task:
    """Задача telegram старше порога; в choosing — если to_choosing, иначе в new."""
    async with factory() as session:
        task = await create_task(
            session,
            kind=TaskKind.PLAN,
            text="добавь экспорт в CSV",
            source=TaskSource.TELEGRAM,
            known_workspace_ids=("demo",),
        )
        if to_choosing:
            task = await change_status(
                session, task.id, TaskStatus.CHOOSING, source=TaskEventSource.TELEGRAM
            )
        await session.execute(
            update(Task).where(Task.id == task.id).values(created_at=datetime.now(UTC) - OLD)
        )
        await session.commit()
    return task


async def test_recover_sends_missing_card(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _aged_task(committed_session_factory, to_choosing=True)

    await recover_pending(ctx)

    assert len(fake.sent) == 1
    async with committed_session_factory() as session:
        card = await session.get(TelegramMessage, task.id)
    assert card is not None
    assert card.lines == ["Задача [добавь экспорт в CSV] (выберите проект)"]


async def test_recover_moves_new_task_to_choosing(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    task = await _aged_task(committed_session_factory, to_choosing=False)

    await recover_pending(ctx)

    async with committed_session_factory() as session:
        stored = await session.get(Task, task.id)
        card_rows = (
            await session.execute(select(TelegramMessage).where(TelegramMessage.task_id == task.id))
        ).all()
    assert stored is not None
    assert stored.status == TaskStatus.CHOOSING
    assert len(card_rows) == 1
    assert len(fake.sent) == 1


async def test_failed_processing_keeps_update_for_retry(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    kind, external_id = await _insert_update(
        committed_session_factory,
        telegram_update("text_message"),
        received_at=datetime.now(UTC) - OLD,
    )

    async def broken_create(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(intake, "create_task", broken_create)
    await recover_pending(ctx)

    # Сбой до отметки processed_at: строка и payload остаются для следующего запуска.
    row = await _update_row(committed_session_factory, kind, external_id)
    assert row.processed_at is None
    assert row.payload is not None

    monkeypatch.undo()
    await recover_pending(ctx)

    row = await _update_row(committed_session_factory, kind, external_id)
    assert row.processed_at is not None
    assert row.payload is None
    assert await _task_count(committed_session_factory) == 1


async def test_expired_update_payload_dropped_without_processing(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    telegram_update: Callable[[str], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ядовитый апдейт старше PAYLOAD_TTL: его не обрабатывают, а payload очищают (S2a).
    fake = FakeTelegramClient()
    ctx = make_bot_context(committed_session_factory, telegram=fake)
    kind, external_id = await _insert_update(
        committed_session_factory,
        telegram_update("text_message"),
        received_at=datetime.now(UTC) - PAYLOAD_TTL - timedelta(hours=1),
    )

    async def must_not_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("expired update must not be processed")

    monkeypatch.setattr(intake, "create_task", must_not_run)
    processed = await recover_pending(ctx)

    assert processed == 1
    row = await _update_row(committed_session_factory, kind, external_id)
    assert row.processed_at is not None
    assert row.payload is None
    assert await _sql_null_payload_count(committed_session_factory) == 1
    # Литеральный SQL: проверяет, что после TTL-списания в колонке именно NULL (D-27).
    async with committed_session_factory() as session:
        raw = await session.execute(
            text(
                "select count(*) from telegram_updates "
                "where payload is null and processed_at is not null"
            )
        )
        assert raw.scalar_one() == 1
    assert await _task_count(committed_session_factory) == 0
    assert fake.sent == []
