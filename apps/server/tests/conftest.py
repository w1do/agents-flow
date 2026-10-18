"""Общие фикстуры: изоляция ENV, пример harness.yaml, Postgres (TEST_DATABASE_URL или контейнер)."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_CONFIG = REPO_ROOT / "config" / "harness.example.yaml"

# Все переменные из Settings. Тесты очищают их, чтобы окружение разработчика не влияло на результат.
ALL_ENV_NAMES = (
    "DATABASE_URL",
    "HARNESS_CONFIG",
    "HARNESS_SECRET_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_WEBHOOK_SECRET",
    "HARNESS_PUBLIC_URL",
    "HARNESS_ADMIN_TOKEN",
    "POLZA_AI_URL",
    "POLZA_AI_KEY",
    "POLZA_AI_MODEL",
    "ROUTING_MIN_CONFIDENCE",
    "STT_PROVIDER",
    "STT_API_URL",
    "STT_API_KEY",
    "STT_MODEL",
    "NOVITA_API_KEY",
    "NOVITA_DOMAIN",
    "GITLAB_URL",
    "GITLAB_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "AGENT_RUN_TIMEOUT_MIN",
    "TESTS_TIMEOUT_MIN",
    "ADMIN_EMAIL",
    "ADMIN_PASSWORD",
    "WORKER_POLL_INTERVAL_SEC",
)

VALID_SECRET_KEY = "test-secret-key-0123456789abcdef0123"

# Адрес, на котором никто не слушает: подключение падает сразу, без ожидания таймаута.
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://u:p@127.0.0.1:1/x"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убирает переменные харнесса из окружения каждого теста."""
    for name in ALL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Полный набор обязательных ENV с путём к примеру harness.yaml."""
    values = {
        "DATABASE_URL": UNREACHABLE_DATABASE_URL,
        "HARNESS_CONFIG": str(EXAMPLE_CONFIG),
        # Минимум 32 символа (D-20); значение тестовое, не настоящий секрет.
        "HARNESS_SECRET_KEY": VALID_SECRET_KEY,
        "TELEGRAM_BOT_TOKEN": "123:test-bot-token",
        "TELEGRAM_CHAT_ID": "424242",
        "TELEGRAM_WEBHOOK_SECRET": "test-webhook-secret",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """URL тестовой Postgres. В CI задаётся TEST_DATABASE_URL; локально поднимается контейнер."""
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        yield external
        return

    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def migrated_database_url(database_url: str) -> Iterator[str]:
    """Миграции до head один раз за сессию (синхронно: env.py сам вызывает asyncio.run)."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        alembic_command.upgrade(AlembicConfig(str(REPO_ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    yield database_url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Один engine на сессию: asyncpg привязан к циклу событий session."""
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия во внешней транзакции; commit сервиса → SAVEPOINT; в конце всё откатывается."""
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


# Очистка после тестов с настоящими коммитами; порядок не важен, CASCADE снимает зависимости.
TRUNCATE_ALL = (
    "TRUNCATE TABLE telegram_updates, telegram_messages, task_tokens, sandboxes, spec_items, "
    "checkpoints, routings, task_events, tasks CASCADE"
)


@pytest_asyncio.fixture(loop_scope="session")
async def committed_session_factory(
    db_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Настоящие коммиты на отдельных соединениях (SKIP LOCKED, HTTP). После теста — TRUNCATE."""
    yield async_sessionmaker(db_engine, expire_on_commit=False)
    async with db_engine.begin() as connection:
        await connection.execute(text(TRUNCATE_ALL))
