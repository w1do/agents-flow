"""Сценарий 3.3: alembic upgrade head на пустой БД проходит через команду migrate (и повторно)."""

from pathlib import Path

import pytest
from harness_server.cli import app
from typer.testing import CliRunner

REPO_ROOT_ALEMBIC_INI = str(Path(__file__).resolve().parents[3] / "alembic.ini")


def test_migrate_upgrades_empty_database(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    runner = CliRunner()

    first = runner.invoke(app, ["migrate", "--alembic-config", REPO_ROOT_ALEMBIC_INI])
    second = runner.invoke(app, ["migrate", "--alembic-config", REPO_ROOT_ALEMBIC_INI])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output


def test_migrate_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    result = CliRunner().invoke(app, ["migrate", "--alembic-config", REPO_ROOT_ALEMBIC_INI])

    assert result.exit_code != 0
    assert "DATABASE_URL" in result.output
