"""Фильтр секретов: шаблоны токенов и точные значения из настроек."""

from harness_server.security.redaction import REDACTED, redact

TELEGRAM_TOKEN = "123456:TEST-TOKEN-abcdefghijklmnopqrstuvwxyz0123"
GITLAB_TOKEN = "glpat-abcdefghijklmnopqrst1234"
ANTHROPIC_KEY = "sk-ant-api03-abcdefghijklmnopqrstuv"


def test_redacts_telegram_token() -> None:
    assert redact(f"token {TELEGRAM_TOKEN} end") == f"token {REDACTED} end"


def test_redacts_telegram_token_inside_url() -> None:
    # Bot API кладёт токен в путь: «/bot<id>:<secret>/method», перед цифрами стоит буква.
    token = "123456789:" + "A1_-" * 8 + "A1_"
    assert len(token.split(":")[1]) == 35
    url = f"https://api.telegram.org/bot{token}/getMe"

    assert redact(url) == f"https://api.telegram.org/bot{REDACTED}/getMe"


def test_redacts_gitlab_token() -> None:
    assert redact(f"token {GITLAB_TOKEN} end") == f"token {REDACTED} end"


def test_redacts_anthropic_key() -> None:
    assert redact(f"key={ANTHROPIC_KEY}") == f"key={REDACTED}"


def test_redacts_bearer_keeps_scheme() -> None:
    text = "Authorization: Bearer abcdefghijklmnop1234"

    assert redact(text) == f"Authorization: Bearer {REDACTED}"


def test_redacts_extra_values() -> None:
    secret = "s3cr3t-value-xyz"

    assert redact(f"text has {secret} inside", [secret]) == f"text has {REDACTED} inside"


def test_short_extra_values_ignored() -> None:
    text = "code abc123 stays"

    assert redact(text, ["abc"]) == text


def test_longer_extra_value_replaced_before_its_part() -> None:
    # Короткое значение внутри длинного: сначала длинное, иначе остался бы хвост секрета.
    assert redact("value: prefix-secret-long", ["prefix-secret", "prefix-secret-long"]) == (
        f"value: {REDACTED}"
    )


def test_text_without_secrets_unchanged() -> None:
    text = "добавь экспорт в CSV: 2 строки, без токенов"

    assert redact(text) == text
