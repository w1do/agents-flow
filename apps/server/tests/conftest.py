"""Общие фикстуры: изоляция ENV, пример harness.yaml, Postgres (TEST_DATABASE_URL или контейнер)."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_CONFIG = REPO_ROOT / "config" / "harness.example.yaml"

# Все переменные из Settings. Тесты очищают их, чтобы окружение разработчика не влияло на результат.
ALL_ENV_NAMES = (
    "DATABASE_URL",
    "HARNESS_CONFIG",
    "HARNESS_SECRET_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_WEBHOOK_SECRET",
    "HARNESS_PUBLIC_URL",
    "HARNESS_ADMIN_TOKEN",
    "POLZA_AI_URL",
    "POLZA_AI_KEY",
    "POLZA_AI_MODEL",
    "ROUTING_MIN_CONFIDENCE",
    "STT_PROVIDER",
    "STT_API_URL",
    "STT_API_KEY",
    "STT_MODEL",
    "NOVITA_API_KEY",
    "NOVITA_DOMAIN",
    "GITLAB_URL",
    "GITLAB_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "AGENT_RUN_TIMEOUT_MIN",
    "TESTS_TIMEOUT_MIN",
    "ADMIN_EMAIL",
    "ADMIN_PASSWORD",
    "WORKER_POLL_INTERVAL_SEC",
)

VALID_SECRET_KEY = "test-secret-key-0123456789abcdef0123"

# Адрес, на котором никто не слушает: подключение падает сразу, без ожидания таймаута.
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://u:p@127.0.0.1:1/x"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убирает переменные харнесса из окружения каждого теста."""
    for name in ALL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Полный набор обязательных ENV с путём к примеру harness.yaml."""
    values = {
        "DATABASE_URL": UNREACHABLE_DATABASE_URL,
        "HARNESS_CONFIG": str(EXAMPLE_CONFIG),
        # Минимум 32 символа (D-20); значение тестовое, не настоящий секрет.
        "HARNESS_SECRET_KEY": VALID_SECRET_KEY,
        "TELEGRAM_BOT_TOKEN": "123:test-bot-token",
        "TELEGRAM_CHAT_ID": "424242",
        "TELEGRAM_WEBHOOK_SECRET": "test-webhook-secret",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """URL тестовой Postgres. В CI задаётся TEST_DATABASE_URL; локально поднимается контейнер."""
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        yield external
        return

    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container.get_connection_url()
