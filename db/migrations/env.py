"""Окружение Alembic на async engine. URL берётся из DATABASE_URL; метаданные — Base.metadata.

Импорт пакета моделей регистрирует все таблицы MVP, поэтому autogenerate и alembic check видят
схему.
"""

import asyncio
import os
from logging.config import fileConfig

import harness_server.db.models  # noqa: F401  регистрирует таблицы в Base.metadata
from alembic import context
from harness_server.db.base import Base
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: миграции запускаются в процессе приложения
    # (harness-server migrate), и без этого флага логгеры harness_server.* уже созданных
    # модулей отключаются молча.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL не задан: миграции читают URL только из окружения")
    return url


def run_migrations_offline() -> None:
    """Генерация SQL без подключения к БД (alembic upgrade --sql)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    # NullPool: миграционное соединение не должно оставаться открытым после upgrade.
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    """Применение миграций к БД. Вызывается синхронно из CLI, asyncio.run здесь собственный."""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
