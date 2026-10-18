"""CLI harness-server через CliRunner: help, check-config, отказ при неполных ENV."""

import inspect
import logging

import pytest
from harness_server import wiring
from harness_server.adapters.telegram import FakeTelegramClient, TelegramError
from harness_server.cli import _configure_logging, app
from harness_server.wiring import BotAdapters
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
