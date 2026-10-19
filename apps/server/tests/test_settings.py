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

    assert settings.routing_min_confidence == 0.6
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
    # 33 символа: алфавит Telegram и минимум 32 символа одновременно.
    secret = "Abc_123-xyz" * 3
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", secret)

    settings = load_settings()

    assert settings.telegram_webhook_secret.get_secret_value() == secret


def test_webhook_secret_too_short_rejected(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    # Один символ, но допустимый алфавит: отклоняет именно минимальная длина.
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "Q")

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "TELEGRAM_WEBHOOK_SECRET" in str(info.value)


def test_webhook_secret_32_chars_accepted(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "w" * 32)

    settings = load_settings()

    assert len(settings.telegram_webhook_secret.get_secret_value()) == 32


def test_chat_id_must_be_numeric(valid_env: dict[str, str], monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "abc")

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "TELEGRAM_CHAT_ID" in str(info.value)


@pytest.mark.parametrize("value", ["-1001234567890", "0"])
def test_group_or_zero_chat_id_rejected(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, value: str
) -> None:
    # Группы не поддерживаются (D-30): владелец — личный чат с положительным id.
    monkeypatch.setenv("TELEGRAM_CHAT_ID", value)

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "TELEGRAM_CHAT_ID" in message
    # Значение id в тексте не выводится. Для «0» проверка бессмысленна: «0» есть в «D-30».
    if value != "0":
        assert value not in message


def test_positive_chat_id_accepted(valid_env: dict[str, str], monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")

    settings = load_settings()

    assert settings.telegram_chat_id == "123456789"


def test_stt_api_url_must_be_https(valid_env: dict[str, str], monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("STT_API_URL", "http://stt.example.com/v1")

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "STT_API_URL" in message
    assert "stt.example.com" not in message


def test_stt_api_url_https_accepted(valid_env: dict[str, str], monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("STT_API_URL", "https://stt.example.com/v1")

    settings = load_settings()

    assert settings.stt_api_url == "https://stt.example.com/v1"


def test_stt_provider_unknown_rejected(valid_env: dict[str, str], monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("STT_PROVIDER", "whisper-local")

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "STT_PROVIDER" in str(info.value)


def test_voice_max_bytes_default(valid_env: dict[str, str]) -> None:
    settings = load_settings()

    assert settings.voice_max_bytes == 20 * 1024 * 1024


def test_voice_max_bytes_over_limit_rejected(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    # Один байт сверх лимита getFile Telegram (20 МиБ).
    monkeypatch.setenv("VOICE_MAX_BYTES", str(20 * 1024 * 1024 + 1))

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "VOICE_MAX_BYTES" in str(info.value)


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


def test_polza_ai_url_requires_https(valid_env: dict[str, str], monkeypatch: MonkeyPatch) -> None:
    # Текст владельца уходит в Polza: открытый http недопустим (D-31).
    monkeypatch.setenv("POLZA_AI_URL", "http://polza.ai/api/v1")

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "POLZA_AI_URL" in str(info.value)


def test_routing_min_confidence_out_of_range_rejected(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("ROUTING_MIN_CONFIDENCE", "1.5")

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "ROUTING_MIN_CONFIDENCE" in str(info.value)


def test_vault_mcp_url_must_be_https(valid_env: dict[str, str], monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_MCP_URL", "http://vault.example/mcp")

    with pytest.raises(SettingsError) as info:
        load_settings()

    assert "VAULT_MCP_URL" in str(info.value)


def test_vault_settings_optional_and_token_hidden(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    assert load_settings().vault_mcp_url is None
    assert load_settings().vault_mcp_token is None

    monkeypatch.setenv("VAULT_MCP_URL", "https://vault.example/mcp")
    monkeypatch.setenv("VAULT_MCP_TOKEN", "vault-token-test-0123456789abcdef")
    settings = load_settings()

    assert settings.vault_mcp_url == "https://vault.example/mcp"
    assert "vault-token-test" not in repr(settings)


def test_telegram_api_url_defaults_to_bot_api(valid_env: dict[str, str]) -> None:
    settings = load_settings()

    assert settings.telegram_api_url == "https://api.telegram.org"


def test_telegram_api_url_empty_means_default(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_API_URL", "")

    assert load_settings().telegram_api_url == "https://api.telegram.org"


def test_telegram_api_url_must_be_https(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    # Токен бота стоит в пути URL: открытый http его раскроет (D-61).
    monkeypatch.setenv("TELEGRAM_API_URL", "http://proxy.example.com")

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "TELEGRAM_API_URL" in message
    assert "proxy.example.com" not in message


@pytest.mark.parametrize(
    "url",
    [
        f"https://user:{LEAK_MARKER}@proxy.example.com",
        f"https://{LEAK_MARKER}@proxy.example.com",
        "https://proxy.example.com?token=1",
        "https://proxy.example.com/#frag",
    ],
)
def test_telegram_api_url_rejects_credentials_query_fragment(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("TELEGRAM_API_URL", url)

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "TELEGRAM_API_URL" in message
    assert LEAK_MARKER not in message


def test_telegram_api_url_trailing_slash_stripped(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_API_URL", "https://proxy.example.com/tg/")

    settings = load_settings()

    assert settings.telegram_api_url == "https://proxy.example.com/tg"


# Строгие правила адресов (D-61): пробелы, управляющие символы, регистр схемы, хост, порт.
BAD_URLS = [
    "http://x.example.com",
    "https://x.example.com:99999",
    "https://x\n.example.com",
    "HTTPS://x.example.com",
    " https://x.example.com",
    "https://:443",
    "https://user@x.example.com",
    "https://x.example.com?token=1",
]


@pytest.mark.parametrize("url", BAD_URLS)
def test_telegram_api_url_strict_rules(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("TELEGRAM_API_URL", url)

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "TELEGRAM_API_URL" in message
    assert "x.example.com" not in message


@pytest.mark.parametrize("url", BAD_URLS)
def test_telegram_webhook_url_strict_rules(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", url)

    with pytest.raises(SettingsError) as info:
        load_settings()

    message = str(info.value)
    assert "TELEGRAM_WEBHOOK_URL" in message
    assert "x.example.com" not in message


def test_telegram_webhook_url_unset_is_none(valid_env: dict[str, str]) -> None:
    assert load_settings().telegram_webhook_url is None


def test_telegram_webhook_url_empty_means_unset(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "")

    assert load_settings().telegram_webhook_url is None


def test_telegram_webhook_url_keeps_path(
    valid_env: dict[str, str], monkeypatch: MonkeyPatch
) -> None:
    # Путь маршрута Worker нужен как есть: слеш в конце не отрезается.
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://tg.example.com/tg-webhook")

    assert load_settings().telegram_webhook_url == "https://tg.example.com/tg-webhook"
