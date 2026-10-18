"""Миграция 0001 и Alembic: схема совпадает с ORM, откат и повтор, логгеры при миграции
(platform-config)."""

import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

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


def test_migrate_keeps_application_loggers_enabled(
    monkeypatch: pytest.MonkeyPatch, migrated_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    # Логгер не из alembic.ini: без disable_existing_loggers=False fileConfig отключил бы его.
    logger = logging.getLogger("harness_server.probe")

    command.upgrade(_alembic_config(), "head")

    assert logger.disabled is False
