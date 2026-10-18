"""CLI harness-server через CliRunner: help, check-config, отказ при неполных ENV."""

import inspect

import pytest
from harness_server.cli import app
from typer.testing import CliRunner

MonkeyPatch = pytest.MonkeyPatch
runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("serve", "worker", "migrate", "check-config"):
        assert command in result.output


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
