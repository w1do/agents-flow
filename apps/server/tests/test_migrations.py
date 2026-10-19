"""Миграция 0001 и Alembic: схема совпадает с ORM, откат и повтор, логгеры при миграции
(platform-config)."""

import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[3]


def _alembic_config() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


def test_alembic_check_reports_no_diff(
    monkeypatch: pytest.MonkeyPatch, migrated_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)

    # alembic check поднимает исключение при любом расхождении ORM и БД.
    command.check(_alembic_config())


def test_downgrade_and_upgrade_roundtrip(
    monkeypatch: pytest.MonkeyPatch, migrated_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    config = _alembic_config()

    command.downgrade(config, "base")
    command.upgrade(config, "head")

    command.check(config)


@pytest.mark.asyncio
async def test_telegram_updates_payload_column(migrated_database_url: str) -> None:
    # Ревизия 0002: nullable JSONB, без неё до обработки нечего дообрабатывать после рестарта.
    engine = create_async_engine(migrated_database_url)
    try:
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync_conn: inspect(sync_conn).get_columns("telegram_updates")
            )
    finally:
        await engine.dispose()

    payload = next(column for column in columns if column["name"] == "payload")
    assert payload["nullable"] is True
    assert isinstance(payload["type"], postgresql.JSONB)


def test_migrate_keeps_application_loggers_enabled(
    monkeypatch: pytest.MonkeyPatch, migrated_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    # Логгер не из alembic.ini: без disable_existing_loggers=False fileConfig отключил бы его.
    logger = logging.getLogger("harness_server.probe")

    command.upgrade(_alembic_config(), "head")

    assert logger.disabled is False


@pytest.mark.asyncio
async def test_routings_schema_after_0003(migrated_database_url: str) -> None:
    # Ревизия 0003 (mvp-05, D-32): решение без задачи, причина запасного пути, уточнение.
    engine = create_async_engine(migrated_database_url)
    try:
        async with engine.connect() as connection:
            columns, checks = await connection.run_sync(
                lambda sync_conn: (
                    inspect(sync_conn).get_columns("routings"),
                    inspect(sync_conn).get_check_constraints("routings"),
                )
            )
    finally:
        await engine.dispose()

    by_name = {column["name"]: column for column in columns}
    assert by_name["task_id"]["nullable"] is True
    assert by_name["decision"]["nullable"] is False
    assert getattr(by_name["command_class"]["type"], "length", None) == 16
    for name in ("error", "source_text", "resolved_at"):
        assert name in by_name
    check_names = {check["name"] for check in checks}
    assert "ck_routings_decision" in check_names
    assert "ck_routings_command_class" in check_names


@pytest.mark.asyncio
async def test_sandboxes_agent_columns_after_0004(migrated_database_url: str) -> None:
    # Ревизия 0004 (mvp-06, D-41): серверный учёт запуска агента — время и pid, оба nullable.
    engine = create_async_engine(migrated_database_url)
    try:
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync_conn: inspect(sync_conn).get_columns("sandboxes")
            )
    finally:
        await engine.dispose()

    by_name = {column["name"]: column for column in columns}
    assert by_name["agent_started_at"]["nullable"] is True
    assert by_name["agent_pid"]["nullable"] is True
