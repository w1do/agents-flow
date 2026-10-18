"""Сценарий platform-config 1: ENV проверяются до старта, ошибка не содержит значений."""

import pytest
from harness_server.settings import SettingsError, load_settings

MonkeyPatch = pytest.MonkeyPatch

# Маркер для проверки утечки: в тексте ошибки его быть не должно. Длина ключа проходит проверку.
LEAK_MARKER = "s3cr3t-value-0123456789abcdef0123"
VALID_SECRET_KEY = "test-secret-key-0123456789abcdef0123"


def test_missing_required_variable_is_named(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "TELEGRAM_BOT_TOKEN" in str(info.value)


def test_error_does_not_leak_other_values(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_SECRET_KEY", LEAK_MARKER)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "TELEGRAM_BOT_TOKEN" in message
    assert LEAK_MARKER not in message
    assert "987654321" not in message


def test_empty_required_variable_counts_as_missing(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "")

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "TELEGRAM_WEBHOOK_SECRET" in str(info.value)


def test_optional_defaults_applied(valid_env: dict[str, str]) -> None:
    settings = load_settings()

    assert settings.routing_min_confidence == 0.7
    assert settings.agent_run_timeout_min == 60
    assert settings.tests_timeout_min == 15
    assert settings.worker_poll_interval_sec == 5.0
    assert settings.polza_ai_key is None


def test_secret_fields_are_not_printed(valid_env: dict[str, str]) -> None:
    settings = load_settings()

    assert VALID_SECRET_KEY not in repr(settings)
    assert settings.harness_secret_key.get_secret_value() == VALID_SECRET_KEY


def test_invalid_poll_interval_rejected(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SEC", "0")

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "WORKER_POLL_INTERVAL_SEC" in str(info.value)


@pytest.mark.parametrize("value", ["", "short", "x" * 31])
def test_short_secret_key_rejected_without_value(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HARNESS_SECRET_KEY", value)

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "HARNESS_SECRET_KEY" in message
    if value:
        assert value not in message


@pytest.mark.parametrize("value", ["has space", "bad!char", "слово", "a" * 257])
def test_invalid_webhook_secret_rejected_without_value(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", value)

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "TELEGRAM_WEBHOOK_SECRET" in message
    assert value not in message


def test_webhook_secret_accepts_telegram_alphabet(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "Abc_123-xyz")

    settings = load_settings()

    assert settings.telegram_webhook_secret.get_secret_value() == "Abc_123-xyz"


def test_admin_token_too_short_rejected(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    # 31 символ: на один меньше минимума; значение не должно попасть в текст ошибки (D-23).
    short_token = "a" * 31
    monkeypatch.setenv("HARNESS_ADMIN_TOKEN", short_token)

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "HARNESS_ADMIN_TOKEN" in message
    assert short_token not in message


def test_admin_token_min_length_accepted(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_ADMIN_TOKEN", "b" * 32)

    settings = load_settings()

    assert settings.harness_admin_token is not None
    assert len(settings.harness_admin_token.get_secret_value()) == 32


def test_admin_token_optional(valid_env: dict[str, str]) -> None:
    settings = load_settings()

    assert settings.harness_admin_token is None


@pytest.mark.parametrize(
    "token",
    [" " * 32, " " + "c" * 32, "c" * 32 + " ", "\t" + "c" * 32 + "\n"],
)
def test_admin_token_surrounding_whitespace_rejected(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, token: str
) -> None:
    # Пробелы по краям отклоняются, даже когда длина без них достаточна; значение не выводится.
    monkeypatch.setenv("HARNESS_ADMIN_TOKEN", token)

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "HARNESS_ADMIN_TOKEN" in message
    assert "c" * 32 not in message
