"""Граница ENV: worker — WorkerSettings, миграции — DATABASE_URL, HTTP-сервер — Settings."""

from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from conftest import EXAMPLE_CONFIG
from harness_server import cli
from harness_server.config import HarnessConfig
from harness_server.worker.settings import WorkerSettings
from pydantic import SecretStr
from typer.testing import CliRunner

runner = CliRunner()
SERVER_ENV = (
    "DATABASE_URL",
    "HARNESS_SECRET_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_WEBHOOK_SECRET",
)


@pytest.fixture
def worker_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    values = {
        "HARNESS_CONFIG": str(EXAMPLE_CONFIG),
        "HARNESS_PUBLIC_URL": "http://127.0.0.1:8000",
        "WORKER_API_TOKEN": "test-worker-token-0123456789abcdef01",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


@pytest.mark.parametrize("with_credentials", [False, True])
def test_worker_cli_loads_only_worker_settings(
    worker_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, with_credentials: bool
) -> None:
    credentials = {
        "CLAUDE_CODE_OAUTH_TOKEN": "test-oauth-token",
        "VAULT_MCP_URL": "https://vault.test/mcp",
        "VAULT_MCP_TOKEN": "test-vault-token",
    }
    if with_credentials:
        for name, value in credentials.items():
            monkeypatch.setenv(name, value)
    calls: list[tuple[WorkerSettings, HarnessConfig]] = []

    async def serve_worker(settings: WorkerSettings, config: HarnessConfig) -> None:
        calls.append((settings, config))

    monkeypatch.setattr(cli, "serve_worker", serve_worker)
    result = runner.invoke(cli.app, ["worker"])

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    settings, config = calls[0]
    assert isinstance(settings, WorkerSettings)
    assert settings.harness_config == Path(worker_env["HARNESS_CONFIG"])
    assert settings.harness_public_url == worker_env["HARNESS_PUBLIC_URL"]
    assert settings.worker_api_token.get_secret_value() == worker_env["WORKER_API_TOKEN"]
    assert config.sandbox.provider_id
    for name in SERVER_ENV:
        assert not hasattr(settings, name.lower())
    for name, value in credentials.items():
        actual = getattr(settings, name.lower())
        if isinstance(actual, SecretStr):
            actual = actual.get_secret_value()
        assert actual == (value if with_credentials else None)
    assert "Ошибка конфигурации" not in result.output


@pytest.mark.parametrize("name", ["HARNESS_CONFIG", "HARNESS_PUBLIC_URL", "WORKER_API_TOKEN"])
@pytest.mark.parametrize("value", [None, ""])
def test_worker_cli_rejects_missing_worker_env(
    worker_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, name: str, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)

    result = runner.invoke(cli.app, ["worker"])

    assert result.exit_code == 1
    assert name in result.output
    assert worker_env["WORKER_API_TOKEN"] not in result.output
    assert all(server_name not in result.output for server_name in SERVER_ENV)


def test_worker_cli_rejects_missing_config(
    worker_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv("HARNESS_CONFIG", str(missing))

    result = runner.invoke(cli.app, ["worker"])

    assert result.exit_code == 1
    assert str(missing) in result.output
    assert worker_env["WORKER_API_TOKEN"] not in result.output


@pytest.mark.parametrize("command", ["serve", "check-config"])
@pytest.mark.parametrize("name", [*SERVER_ENV, "HARNESS_CONFIG"])
@pytest.mark.parametrize("value", [None, ""])
def test_server_commands_require_full_env(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    name: str,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)

    result = runner.invoke(cli.app, [command])

    assert result.exit_code == 1
    assert name in result.output


def test_migrate_with_only_database_url_runs_alembic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/x")
    calls: list[tuple[str | None, str]] = []

    def upgrade(config: AlembicConfig, revision: str) -> None:
        calls.append((config.config_file_name, revision))

    monkeypatch.setattr(alembic_command, "upgrade", upgrade)
    result = runner.invoke(cli.app, ["migrate", "--alembic-config", "custom.ini"])

    assert result.exit_code == 0, result.output
    assert calls == [("custom.ini", "head")]


@pytest.mark.parametrize("value", [None, ""])
def test_migrate_requires_nonempty_database_url(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is not None:
        monkeypatch.setenv("DATABASE_URL", value)

    result = runner.invoke(cli.app, ["migrate"])

    assert result.exit_code == 1
    assert "DATABASE_URL" in result.output
