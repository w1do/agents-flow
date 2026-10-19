"""CLI harness-server через CliRunner: help, check-config, отказ при неполных ENV, песочница."""

import asyncio
import inspect
import logging
from pathlib import Path

import pytest
import yaml
from harness_server import wiring
from harness_server.adapters.novita import FakeSandbox
from harness_server.adapters.telegram import FakeTelegramClient, TelegramError
from harness_server.adapters.vault import FakeVault, VaultError
from harness_server.cli import _configure_logging, app
from harness_server.config import load_config
from harness_server.services import sandboxes
from harness_server.services.tasks import create_task
from harness_server.vault_ref import VaultRef
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
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings: fake)
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
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings: fake)
    asyncio.run(_truncate(migrated_database_url))
    try:
        result = runner.invoke(app, ["sandbox", command])
    finally:
        asyncio.run(_truncate(migrated_database_url))

    assert result.exit_code == 0, result.output
    assert done in result.output
    assert "sandbox_not_registered" not in result.output


def test_sandbox_bootstrap_refuses_busy_sandbox(
    valid_env: dict[str, str],
    monkeypatch: MonkeyPatch,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    """Bootstrap во время активной задачи не выполняется: код 1, понятная ошибка (пункт I)."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test-token-0123456789abcdef")
    config_path = Path(valid_env["HARNESS_CONFIG"])
    fake = FakeSandbox(sandbox_id=load_config(config_path).sandbox.provider_id)
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings: fake)
    script = tmp_path / "bootstrap.sh"
    script.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    asyncio.run(_occupy_sandbox(migrated_database_url, config_path))
    try:
        result = runner.invoke(app, ["sandbox", "bootstrap", "--script", str(script)])
    finally:
        asyncio.run(_truncate(migrated_database_url))

    assert result.exit_code == 1, result.output
    assert "занята" in result.output
    assert fake.journal == []


# --- sandbox-profile: sandbox bootstrap с ключами из vault и памятью (design 6) ---

VAULT_GITLAB = "glpat-vault-value-0123456789abcdef"
VAULT_EMBEDDING = "emb-vault-value-0123456789abcdef"
# Фиктивный sha для тестов (D-51): настоящий закреплённый коммит — только в harness.yaml и D-51.
MEMORY_REF = "0123456789abcdef0123456789abcdef01234567"


def _write_vault_config(tmp_path: Path, valid_env: dict[str, str], *, memory: bool) -> Path:
    """Копия примера harness.yaml со ссылками на vault; memory — блок памяти с embedding_ref."""
    data = load_config(Path(valid_env["HARNESS_CONFIG"])).model_dump(mode="json")
    data["gitlab"]["access_ref"] = "vault:demo/gitlab/main"
    if memory:
        data["sandbox"]["memory"] = {
            "ref": MEMORY_REF,
            "embedding_ref": "vault:demo/polza/embeddings",
        }
    path = tmp_path / "harness.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _bootstrap_script(tmp_path: Path) -> Path:
    script = tmp_path / "bootstrap.sh"
    script.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    return script


def test_sandbox_bootstrap_takes_keys_from_vault_into_env(
    valid_env: dict[str, str],
    monkeypatch: MonkeyPatch,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv("HARNESS_CONFIG", str(_write_vault_config(tmp_path, valid_env, memory=True)))
    fake = FakeSandbox(
        sandbox_id=load_config(Path(valid_env["HARNESS_CONFIG"])).sandbox.provider_id
    )
    vault = FakeVault(
        {
            VaultRef("demo", "gitlab", "main"): VAULT_GITLAB,
            VaultRef("demo", "polza", "embeddings"): VAULT_EMBEDDING,
        }
    )
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings: fake)
    monkeypatch.setattr(wiring, "build_vault", lambda settings: vault)

    result = runner.invoke(
        app, ["sandbox", "bootstrap", "--script", str(_bootstrap_script(tmp_path))]
    )

    assert result.exit_code == 0, result.output
    assert fake.received_env("GITLAB_TOKEN") == VAULT_GITLAB
    assert fake.received_env("EMBEDDING_API_KEY") == VAULT_EMBEDDING
    expected = f"--memory-ref {MEMORY_REF} --memory-repo w1do/memory-agent"
    assert expected in " ".join(e.cmd or "" for e in fake.journal)
    assert VAULT_EMBEDDING not in result.output


def test_sandbox_bootstrap_vault_error_exits_before_provider(
    valid_env: dict[str, str],
    monkeypatch: MonkeyPatch,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv(
        "HARNESS_CONFIG", str(_write_vault_config(tmp_path, valid_env, memory=False))
    )
    fake = FakeSandbox(
        sandbox_id=load_config(Path(valid_env["HARNESS_CONFIG"])).sandbox.provider_id
    )
    vault = FakeVault(fail=VaultError("unavailable", ref="gitlab/main"))
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings: fake)
    monkeypatch.setattr(wiring, "build_vault", lambda settings: vault)

    result = runner.invoke(
        app, ["sandbox", "bootstrap", "--script", str(_bootstrap_script(tmp_path))]
    )

    assert result.exit_code == 1
    assert "Ошибка vault: unavailable" in result.output
    assert fake.journal == []


def test_sandbox_bootstrap_without_any_gitlab_key_exits_one(
    valid_env: dict[str, str],
    monkeypatch: MonkeyPatch,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    fake = FakeSandbox(
        sandbox_id=load_config(Path(valid_env["HARNESS_CONFIG"])).sandbox.provider_id
    )
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings: fake)

    result = runner.invoke(
        app, ["sandbox", "bootstrap", "--script", str(_bootstrap_script(tmp_path))]
    )

    assert result.exit_code == 1
    assert "нужен gitlab.access_ref или GITLAB_TOKEN" in result.output
    assert fake.journal == []


def test_sandbox_bootstrap_redacts_vault_value_in_failure_output(
    valid_env: dict[str, str],
    monkeypatch: MonkeyPatch,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv(
        "HARNESS_CONFIG", str(_write_vault_config(tmp_path, valid_env, memory=False))
    )
    fake = FakeSandbox(
        sandbox_id=load_config(Path(valid_env["HARNESS_CONFIG"])).sandbox.provider_id
    )
    fake.respond("bash /tmp/harness-bootstrap.sh", exit_code=1, stderr=f"ошибка {VAULT_GITLAB}")
    vault = FakeVault({VaultRef("demo", "gitlab", "main"): VAULT_GITLAB})
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings: fake)
    monkeypatch.setattr(wiring, "build_vault", lambda settings: vault)

    result = runner.invoke(
        app, ["sandbox", "bootstrap", "--script", str(_bootstrap_script(tmp_path))]
    )

    assert result.exit_code == 1
    assert VAULT_GITLAB not in result.output
    assert "[REDACTED]" in result.output


def test_sandbox_bootstrap_redacts_auth_header_in_failure_output(
    valid_env: dict[str, str],
    monkeypatch: MonkeyPatch,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    """Заголовок Basic от токена GitLab не попадает в вывод bootstrap (D-52)."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv(
        "HARNESS_CONFIG", str(_write_vault_config(tmp_path, valid_env, memory=False))
    )
    fake = FakeSandbox(
        sandbox_id=load_config(Path(valid_env["HARNESS_CONFIG"])).sandbox.provider_id
    )
    header = sandboxes.git_auth_header(VAULT_GITLAB)
    fake.respond("bash /tmp/harness-bootstrap.sh", exit_code=1, stderr=f"эхо {header}")
    vault = FakeVault({VaultRef("demo", "gitlab", "main"): VAULT_GITLAB})
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings: fake)
    monkeypatch.setattr(wiring, "build_vault", lambda settings: vault)

    result = runner.invoke(
        app, ["sandbox", "bootstrap", "--script", str(_bootstrap_script(tmp_path))]
    )

    assert result.exit_code == 1
    assert header.removeprefix("Authorization: Basic ") not in result.output
    assert "[REDACTED]" in result.output


def test_sandbox_bootstrap_redacts_bare_base64_in_failure_output(
    valid_env: dict[str, str],
    monkeypatch: MonkeyPatch,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    """Голый base64 заголовка (без префикса) в выводе bootstrap редактируется (D-52, ревью)."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv(
        "HARNESS_CONFIG", str(_write_vault_config(tmp_path, valid_env, memory=False))
    )
    fake = FakeSandbox(
        sandbox_id=load_config(Path(valid_env["HARNESS_CONFIG"])).sandbox.provider_id
    )
    _, bare = sandboxes.git_auth_secret_values(VAULT_GITLAB)
    fake.respond("bash /tmp/harness-bootstrap.sh", exit_code=1, stderr=f"эхо {bare}")
    vault = FakeVault({VaultRef("demo", "gitlab", "main"): VAULT_GITLAB})
    monkeypatch.setattr(wiring, "build_sandbox_provider", lambda settings: fake)
    monkeypatch.setattr(wiring, "build_vault", lambda settings: vault)

    result = runner.invoke(
        app, ["sandbox", "bootstrap", "--script", str(_bootstrap_script(tmp_path))]
    )

    assert result.exit_code == 1
    assert bare not in result.output
    assert "[REDACTED]" in result.output
