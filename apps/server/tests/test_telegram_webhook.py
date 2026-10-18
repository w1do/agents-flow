"""Webhook Telegram по HTTP: сценарии «Неверный секрет», «Чужой чат», «Повторная доставка», кнопки.

Приложение собирается как в test_tasks_api.py, с настоящей БД и фейками адаптеров. Фоновая обработка
завершается до ответа ASGI-транспорта, поэтому состояние БД и фейка проверяется сразу после запроса.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.app import create_app
from harness_server.config import load_config
from harness_server.db.models import Task, TelegramMessage, TelegramUpdate
from harness_server.services.tasks import list_task_events, list_tasks
from harness_server.settings import load_settings
from harness_server.wiring import BotAdapters
from harness_shared.tasks import TaskKind, TaskSource, TaskStatus
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
CARD_LINE = "Задача [добавь экспорт в CSV] (выберите проект)"
STAGE_LINE = "Задача [добавь экспорт в CSV] (проект «Демо-проект», планирование)"


@asynccontextmanager
async def _client(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    fake: FakeTelegramClient,
) -> AsyncIterator[httpx.AsyncClient]:
    """Приложение с настоящей БД и фейком Telegram; STT не настроен."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    settings = load_settings()
    app = create_app(
        settings,
        load_config(settings.harness_config),
        adapters=BotAdapters(telegram=fake, stt=None),
    )
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


def _secret(valid_env: dict[str, str]) -> dict[str, str]:
    return {SECRET_HEADER: valid_env["TELEGRAM_WEBHOOK_SECRET"]}


async def _counts(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int, int]:
    """Строки telegram_updates, задачи и карточки в БД."""
    async with factory() as session:
        updates = await session.execute(select(func.count()).select_from(TelegramUpdate))
        tasks = await session.execute(select(func.count()).select_from(Task))
        cards = await session.execute(select(func.count()).select_from(TelegramMessage))
        return int(updates.scalar_one()), int(tasks.scalar_one()), int(cards.scalar_one())


async def _only_task(factory: async_sessionmaker[AsyncSession]) -> Task:
    async with factory() as session:
        tasks = await list_tasks(session)
    assert len(tasks) == 1
    return tasks[0]


async def test_wrong_secret_returns_401(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    headers = {SECRET_HEADER: "wrong-secret-value-that-is-long-enough-0000"}

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        response = await client.post(
            "/telegram/webhook", json=telegram_update("text_message"), headers=headers
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}
    assert await _counts(committed_session_factory) == (0, 0, 0)
    assert fake.sent == []


async def test_missing_secret_returns_401(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        response = await client.post("/telegram/webhook", json=telegram_update("text_message"))

    assert response.status_code == 401
    assert await _counts(committed_session_factory) == (0, 0, 0)
    assert fake.sent == []


async def test_foreign_chat_ignored(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        response = await client.post(
            "/telegram/webhook",
            json=telegram_update("foreign_chat_message"),
            headers=_secret(valid_env),
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert await _counts(committed_session_factory) == (0, 0, 0)
    assert fake.sent == []


async def test_unsupported_update_not_recorded(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        response = await client.post(
            "/telegram/webhook",
            json=telegram_update("start_command"),
            headers=_secret(valid_env),
        )

    assert response.status_code == 200
    assert await _counts(committed_session_factory) == (0, 0, 0)
    assert fake.sent == []


async def test_invalid_json_returns_200(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fake = FakeTelegramClient()

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        response = await client.post(
            "/telegram/webhook",
            content=b"{not json",
            headers={**_secret(valid_env), "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    assert await _counts(committed_session_factory) == (0, 0, 0)


async def test_text_creates_choosing_task_with_buttons(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        response = await client.post(
            "/telegram/webhook",
            json=telegram_update("text_message"),
            headers=_secret(valid_env),
        )

    assert response.status_code == 200
    task = await _only_task(committed_session_factory)
    assert task.kind == TaskKind.PLAN
    assert task.status == TaskStatus.CHOOSING
    assert task.source == TaskSource.TELEGRAM
    assert len(fake.sent) == 1
    buttons = fake.sent[0].reply_markup
    assert buttons is not None
    assert [button.text for row in buttons.rows for button in row] == ["Демо-проект"]
    async with committed_session_factory() as session:
        card = await session.get(TelegramMessage, task.id)
    assert card is not None
    assert card.lines == [CARD_LINE]


async def test_duplicate_delivery_creates_one_task(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()
    raw = telegram_update("text_message")

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        first = await client.post("/telegram/webhook", json=raw, headers=_secret(valid_env))
        second = await client.post("/telegram/webhook", json=raw, headers=_secret(valid_env))

    assert first.status_code == second.status_code == 200
    assert await _counts(committed_session_factory) == (1, 1, 1)
    assert len(fake.sent) == 1


async def test_payload_cleared_after_processing(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        await client.post(
            "/telegram/webhook",
            json=telegram_update("text_message"),
            headers=_secret(valid_env),
        )

    async with committed_session_factory() as session:
        row = await session.get(TelegramUpdate, ("update", "10001"))
    assert row is not None
    assert row.processed_at is not None
    assert row.payload is None
    # D-27: очистка означает SQL NULL, а не JSON 'null'; ORM-проверка обычно пропускает эту разницу.
    async with committed_session_factory() as session:
        cleared = await session.execute(
            select(func.count())
            .select_from(TelegramUpdate)
            .where(TelegramUpdate.payload.is_(None), TelegramUpdate.processed_at.is_not(None))
        )
        assert cleared.scalar_one() == 1
    async with committed_session_factory() as session:
        raw = await session.execute(
            text(
                "select count(*) from telegram_updates "
                "where payload is null and processed_at is not null"
            )
        )
        assert raw.scalar_one() == 1


async def test_button_press_selects_workspace(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        await client.post(
            "/telegram/webhook",
            json=telegram_update("text_message"),
            headers=_secret(valid_env),
        )
        task = await _only_task(committed_session_factory)
        press = telegram_update("callback_query")
        press["callback_query"]["data"] = f"ws:{task.id.hex}:demo"
        response = await client.post("/telegram/webhook", json=press, headers=_secret(valid_env))

    assert response.status_code == 200
    stored = await _only_task(committed_session_factory)
    assert stored.status == TaskStatus.PLANNING
    assert stored.workspace_id == "demo"
    assert fake.callback_answers == [("4242000000000000001", None)]
    assert fake.edits[-1].reply_markup is None
    assert fake.texts[fake.sent[0].message_id].splitlines()[-1] == STAGE_LINE


async def test_duplicate_callback_processed_once(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
) -> None:
    fake = FakeTelegramClient()

    async with _client(monkeypatch, migrated_database_url, fake) as client:
        await client.post(
            "/telegram/webhook",
            json=telegram_update("text_message"),
            headers=_secret(valid_env),
        )
        task = await _only_task(committed_session_factory)
        press = telegram_update("callback_query")
        press["callback_query"]["data"] = f"ws:{task.id.hex}:demo"
        await client.post("/telegram/webhook", json=press, headers=_secret(valid_env))
        # Та же кнопка с тем же callback_query.id, но другим update_id: повторная доставка.
        press["update_id"] = 10009
        await client.post("/telegram/webhook", json=press, headers=_secret(valid_env))

    async with committed_session_factory() as session:
        events = await list_task_events(session, task.id)
    assert [e.status for e in events].count(TaskStatus.PLANNING) == 1
    assert len(fake.callback_answers) == 1
