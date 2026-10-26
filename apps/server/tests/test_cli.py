"""CLI harness-server через CliRunner: help, check-config, отказ при неполных ENV, песочница."""

import asyncio
import inspect
import json
import logging
from pathlib import Path

import httpx
import pytest
import respx
from harness_server import wiring
from harness_server.adapters.sandbox import FakeSandbox
from harness_server.adapters.telegram import FakeTelegramClient, TelegramError
from harness_server.cli import _configure_logging, app
from harness_server.config import load_config
from harness_server.services import sandboxes
from harness_server.services.tasks import create_task
from harness_server.wiring import BotAdapters
from harness_shared.tasks import TaskKind, TaskSource, TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from typer.testing import CliRunner

MonkeyPatch = pytest.MonkeyPatch
runner = CliRunner()


def test_configure_logging_silences_httpx() -> None:
    # Токен Telegram находится в URL запросов httpx: на INFO он попадает в лог.
    _configure_logging()

    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("serve", "worker", "migrate", "check-config", "telegram"):
        assert command in result.output


def _use_fake_telegram(monkeypatch: MonkeyPatch) -> FakeTelegramClient:
    """Подменяет сборку адаптеров: set-webhook не должен ходить в сеть."""
    fake = FakeTelegramClient()

    def build_adapters(settings: object, http: object) -> BotAdapters:
        return BotAdapters(telegram=fake, stt=None)

    monkeypatch.setattr(wiring, "build_adapters", build_adapters)
    return fake


def test_telegram_set_webhook_uses_public_url(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    fake = _use_fake_telegram(monkeypatch)
    monkeypatch.setenv("HARNESS_PUBLIC_URL", "https://harness.example.com/")

    result = runner.invoke(app, ["telegram", "set-webhook"])

    assert result.exit_code == 0, result.output
    assert fake.webhooks == [
        (
            "https://harness.example.com/telegram/webhook",
            valid_env["TELEGRAM_WEBHOOK_SECRET"],
            ("message", "callback_query"),
        )
    ]
    assert "https://harness.example.com/telegram/webhook" in result.output
    assert valid_env["TELEGRAM_WEBHOOK_SECRET"] not in result.output
    assert valid_env["TELEGRAM_BOT_TOKEN"] not in result.output


@pytest.mark.parametrize(
    "public_url", [None, "", "http://harness.example.com", "https://u:p@x.example"]
)
def test_set_webhook_requires_public_url(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, public_url: str | None
) -> None:
    fake = _use_fake_telegram(monkeypatch)
    if public_url is None:
        monkeypatch.delenv("HARNESS_PUBLIC_URL", raising=False)
    else:
        monkeypatch.setenv("HARNESS_PUBLIC_URL", public_url)

    result = runner.invoke(app, ["telegram", "set-webhook"])

    assert result.exit_code == 1
    assert "HARNESS_PUBLIC_URL" in result.output
    assert fake.webhooks == []
    assert valid_env["TELEGRAM_BOT_TOKEN"] not in result.output


def test_set_webhook_without_secret_exits_nonzero(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    fake = _use_fake_telegram(monkeypatch)
    monkeypatch.setenv("HARNESS_PUBLIC_URL", "https://harness.example.com")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET")

    result = runner.invoke(app, ["telegram", "set-webhook"])

    assert result.exit_code != 0
    assert "TELEGRAM_WEBHOOK_SECRET" in result.output
    assert fake.webhooks == []


def test_set_webhook_reports_telegram_error(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    fake = _use_fake_telegram(monkeypatch)
    fake.fail_with = TelegramError("setWebhook", 401, "Unauthorized")
    monkeypatch.setenv("HARNESS_PUBLIC_URL", "https://harness.example.com")

    result = runner.invoke(app, ["telegram", "set-webhook"])

    assert result.exit_code == 1
    assert "Ошибка Telegram" in result.output
    assert valid_env["TELEGRAM_BOT_TOKEN"] not in result.output


def test_check_config_prints_workspaces(valid_env: dict[str, str]) -> None:
    result = runner.invoke(app, ["check-config"])

    assert result.exit_code == 0, result.output
    assert "demo" in result.output


def test_check_config_fails_without_required_variable(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")

    result = runner.invoke(app, ["check-config"])

    assert result.exit_code != 0
    assert "TELEGRAM_BOT_TOKEN" in result.output


def test_serve_without_bot_token_exits_nonzero(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")

    result = runner.invoke(app, ["serve"])

    assert result.exit_code != 0
    assert "TELEGRAM_BOT_TOKEN" in result.output


def test_worker_without_bot_token_exits_nonzero(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")

    result = runner.invoke(app, ["worker"])

    assert result.exit_code != 0
    assert "TELEGRAM_BOT_TOKEN" in result.output


def test_error_output_contains_no_other_secret_values(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    leak_marker = "s3cr3t-value-0123456789abcdef0123"
    monkeypatch.setenv("HARNESS_SECRET_KEY", leak_marker)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")

    result = runner.invoke(app, ["serve"])

    assert result.exit_code != 0
    assert "TELEGRAM_BOT_TOKEN" in result.output
    assert leak_marker not in result.output


def test_serve_defaults_to_localhost() -> None:
    # Открытый 0.0.0.0 задаётся явно (Dockerfile и compose), а не по умолчанию.
    from harness_server.cli import serve

    assert inspect.signature(serve).parameters["host"].default == "127.0.0.1"


@pytest.mark.parametrize("command", ["serve", "worker", "check-config"])
def test_commands_fail_fast_on_missing_config_file(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, command: str
) -> None:
    monkeypatch.setenv("HARNESS_CONFIG", "/nonexistent/harness.yaml")

    result = runner.invoke(app, [command])

    assert result.exit_code != 0
    assert "/nonexistent/harness.yaml" in result.output


class _Stage:
    """Пайплайн для резервирования: реализация из backlog в active."""

    kind = TaskKind.IMPLEMENT
    from_status = TaskStatus.BACKLOG
    to_status: TaskStatus | None = TaskStatus.ACTIVE


async def _occupy_sandbox(url: str, provider_id_source: Path) -> None:
    """Закрепляет песочницу за задачей настоящими коммитами (как worker)."""
    config = load_config(provider_id_source)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await sandboxes.ensure_sandbox(session, config)
        async with factory() as session:
            await create_task(
                session,
                kind=TaskKind.IMPLEMENT,
                text="занятая задача",
                source=TaskSource.API,
                known_workspace_ids=["demo"],
                workspace_id="demo",
            )
        async with factory() as session:
            reservation = await sandboxes.reserve(session, _Stage())
        assert reservation is not None
    finally:
        await engine.dispose()


async def _truncate(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE telegram_updates, telegram_messages, task_tokens, sandboxes, "
                    "spec_items, checkpoints, routings, task_events, tasks CASCADE"
                )
            )
    finally:
        await engine.dispose()


def test_sandbox_pause_refuses_busy_sandbox(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, migrated_database_url: str
) -> None:
    """Пауза занятой песочницы: код 1, понятное сообщение, песочница не паузится (design 9, 4.2)."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    config_path = Path(valid_env["HARNESS_CONFIG"])
    fake = FakeSandbox(sandbox_id=load_config(config_path).sandbox.provider_id)
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings, provider_id: fake)
    asyncio.run(_occupy_sandbox(migrated_database_url, config_path))
    try:
        result = runner.invoke(app, ["sandbox", "pause"])
    finally:
        asyncio.run(_truncate(migrated_database_url))

    assert result.exit_code == 1, result.output
    assert "занята" in result.output
    assert not fake.paused


@pytest.mark.parametrize(("command", "done"), [("pause", "на паузе"), ("resume", "возобновлена")])
def test_sandbox_command_registers_missing_row(
    valid_env: dict[str, str],
    monkeypatch: MonkeyPatch,
    migrated_database_url: str,
    command: str,
    done: str,
) -> None:
    """Строки песочницы ещё нет (worker не стартовал): команда создаёт её и не падает (design 8)."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    config_path = Path(valid_env["HARNESS_CONFIG"])
    fake = FakeSandbox(sandbox_id=load_config(config_path).sandbox.provider_id)
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings, provider_id: fake)
    asyncio.run(_truncate(migrated_database_url))
    try:
        result = runner.invoke(app, ["sandbox", command])
    finally:
        asyncio.run(_truncate(migrated_database_url))

    assert result.exit_code == 0, result.output
    assert done in result.output
    assert "sandbox_not_registered" not in result.output


def test_bootstrap_command_is_removed() -> None:
    result = runner.invoke(app, ["sandbox", "bootstrap"])
    assert result.exit_code == 2
    help_result = runner.invoke(app, ["sandbox", "--help"])
    assert "agent init" in help_result.output


def test_set_webhook_goes_through_configured_telegram_api_url(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    # Прод-сервер в РФ регистрирует webhook через прокси владельца (D-61); без подмены сборки.
    proxy = "https://tg-proxy.example.com"
    monkeypatch.setenv("HARNESS_PUBLIC_URL", "https://harness.example.com")
    monkeypatch.setenv("TELEGRAM_API_URL", proxy)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{proxy}/bot{valid_env['TELEGRAM_BOT_TOKEN']}/setWebhook").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": True})
        )
        result = runner.invoke(app, ["telegram", "set-webhook"])

    assert result.exit_code == 0, result.output
    assert route.called
    assert valid_env["TELEGRAM_BOT_TOKEN"] not in result.output


def test_set_webhook_defaults_to_public_url_path(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_PUBLIC_URL", "https://harness.example.com")
    monkeypatch.setenv("TELEGRAM_API_URL", "https://tg-proxy.example.com")

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(
            f"https://tg-proxy.example.com/bot{valid_env['TELEGRAM_BOT_TOKEN']}/setWebhook"
        ).mock(return_value=httpx.Response(200, json={"ok": True, "result": True}))
        result = runner.invoke(app, ["telegram", "set-webhook"])

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content)["url"] == (
        "https://harness.example.com/telegram/webhook"
    )


def test_set_webhook_uses_telegram_webhook_url_override(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    # Апдейты идут через Worker владельца (D-61); HARNESS_PUBLIC_URL при этом не нужен.
    monkeypatch.delenv("HARNESS_PUBLIC_URL", raising=False)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://tg-worker.example.com/tg-webhook")
    monkeypatch.setenv("TELEGRAM_API_URL", "https://tg-proxy.example.com")

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(
            f"https://tg-proxy.example.com/bot{valid_env['TELEGRAM_BOT_TOKEN']}/setWebhook"
        ).mock(return_value=httpx.Response(200, json={"ok": True, "result": True}))
        result = runner.invoke(app, ["telegram", "set-webhook"])

    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content)["url"] == (
        "https://tg-worker.example.com/tg-webhook"
    )
    assert valid_env["TELEGRAM_BOT_TOKEN"] not in result.output
