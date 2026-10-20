"""Фильтр секретов: шаблоны токенов и точные значения из настроек."""

import pytest
from harness_server.security import tokens
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


GITHUB_CLASSIC_TOKEN = "ghp_" + "A1b2C3d4" * 5
GITHUB_FINE_GRAINED_TOKEN = "github_pat_" + "11ABCDEFG0_" + "x9Y8z7W6v5U4t3S2r1Q0pO" * 2


def test_redacts_github_classic_token() -> None:
    assert redact(f"token {GITHUB_CLASSIC_TOKEN} end") == f"token {REDACTED} end"


def test_redacts_github_fine_grained_token() -> None:
    assert redact(f"token {GITHUB_FINE_GRAINED_TOKEN} end") == f"token {REDACTED} end"


@pytest.mark.parametrize("prefix", ["glpat-", "gldt-", "glrt-"])
def test_redacts_gitlab_token_prefixes(prefix: str) -> None:
    token = prefix + "abcdefghijklmnopqrst1234"

    assert redact(f"token {token} end") == f"token {REDACTED} end"


def test_redacts_basic_auth_header() -> None:
    # Заголовок git: схема Basic остаётся, значение base64 заменяется.
    header = "Authorization: Basic b2F1dGgyOmdscGF0LWFiY2RlZmdoaWprbG1ub3BxcnN0"

    assert redact(header) == f"Authorization: Basic {REDACTED}"


def test_short_basic_word_is_kept() -> None:
    assert redact("basic idea stays") == "basic idea stays"


def test_redacts_anthropic_key() -> None:
    assert redact(f"key={ANTHROPIC_KEY}") == f"key={REDACTED}"


def test_redacts_task_token_without_extra_values() -> None:
    # Токен задачи закрывает шаблон формата: после рестарта worker точного значения уже нет (D-42).
    assert redact(f"err {tokens.generate()} end") == f"err {REDACTED} end"


def test_short_aft_word_is_kept() -> None:
    assert redact("aft_short") == "aft_short"


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


@pytest.mark.parametrize("scheme", ["Basic", "BASIC", "basic"])
def test_redacts_basic_auth_header_any_case(scheme: str) -> None:
    header = f"Authorization: {scheme} b2F1dGgyOmdscGF0LWFiY2RlZmdoaWprbG1ub3BxcnN0"

    assert redact(header) == f"Authorization: {scheme} {REDACTED}"


def test_basic_before_long_word_is_kept() -> None:
    assert redact("basic internationalization") == "basic internationalization"


def test_redacts_git_tokens_after_underscore() -> None:
    github_classic = "ghp_" + "A1b2C3d4" * 5
    github_fine = "github_pat_" + "a1B2c3D4e5F6g7H8i9J0kL"
    gitlab = "glpat-abcdefghijklmnopqrst"

    assert redact(f"TOKEN_{github_classic} end") == f"TOKEN_{REDACTED} end"
    assert redact(f"X_{gitlab} end") == f"X_{REDACTED} end"
    assert redact(f"x_{github_fine} end") == f"x_{REDACTED} end"


def test_redacts_password_in_url() -> None:
    url = "https://oauth2:s3cretvalue@gitlab.com/g/p.git"

    assert redact(url) == f"https://oauth2:{REDACTED}@gitlab.com/g/p.git"


def test_url_without_password_unchanged() -> None:
    assert redact("https://gitlab.com/g/p.git") == "https://gitlab.com/g/p.git"
