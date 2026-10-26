"""Остановка worker по SIGTERM и восстановление Telegram при старте сервера."""

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from conftest import EXAMPLE_CONFIG
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.app import create_app
from harness_server.config import load_config
from harness_server.db.models import TelegramUpdate
from harness_server.services.context import BotContext
from harness_server.services.intake import recover_pending
from harness_server.services.tasks import list_tasks
from harness_server.settings import load_settings
from harness_server.telegram.parse import dedup_key, dump_incoming, parse_update
from harness_server.wiring import BotAdapters
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.parametrize("with_credentials", [False, True])
def test_worker_stops_cleanly_on_sigterm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_credentials: bool
) -> None:
    monkeypatch.setenv("HARNESS_CONFIG", str(EXAMPLE_CONFIG))
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SEC", "0.2")
    monkeypatch.setenv("WORKER_API_TOKEN", "test-worker-token-0123456789abcdef01")
    monkeypatch.setenv("HARNESS_PUBLIC_URL", "http://127.0.0.1:1")
    if with_credentials:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-oauth-token")
        monkeypatch.setenv("VAULT_MCP_URL", "https://vault.test/mcp")
        monkeypatch.setenv("VAULT_MCP_TOKEN", "test-vault-token")
    # Консольный скрипт лежит рядом с интерпретатором venv; так тест не зависит от uv.

    process = subprocess.Popen(
        [sys.executable, "-c", "from harness_server.cli import app; app()", "worker"],
        cwd=tmp_path,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stderr is not None
        # Ждём строку запуска: до этого момента обработчики сигналов ещё не установлены.
        for line in process.stderr:
            if "worker started" in line:
                break
        else:
            pytest.fail("worker не запустился")

        process.send_signal(signal.SIGTERM)
        exit_code = process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    assert exit_code == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_server_startup_runs_telegram_recovery(
    valid_env: dict[str, str],
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Старт сервера обрабатывает старый апдейт; повторный старт не создаёт дублей."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    settings = load_settings()
    config = load_config(settings.harness_config)
    incoming = parse_update(telegram_update("text_message"))
    assert incoming is not None
    kind, external_id = dedup_key(incoming)
    async with committed_session_factory() as session:
        await session.execute(
            postgresql.insert(TelegramUpdate).values(
                kind=kind,
                external_id=external_id,
                payload=dump_incoming(incoming),
                received_at=datetime.now(UTC) - timedelta(minutes=2),
            )
        )
        await session.commit()
    fake = FakeTelegramClient()
    recovered: asyncio.Queue[int] = asyncio.Queue()

    async def observed_recovery(bot: BotContext) -> int:
        count = await recover_pending(bot)
        recovered.put_nowait(count)
        return count

    # Наблюдаем настоящий проход recovery: выход из lifespan отменяет фоновую задачу.
    monkeypatch.setattr(
        "harness_server.services.server_recovery.recover_pending", observed_recovery
    )
    task_ids = []
    for expected_count in (1, 0):
        app = create_app(settings, config, adapters=BotAdapters(telegram=fake, stt=None))
        async with LifespanManager(app):
            assert await asyncio.wait_for(recovered.get(), timeout=5) == expected_count

        async with committed_session_factory() as session:
            tasks = await list_tasks(session)
            row = await session.get(TelegramUpdate, (kind, external_id))
        assert len(tasks) == 1
        assert row is not None
        assert row.processed_at is not None
        assert len(fake.sent) == 1
        task_ids.append(tasks[0].id)
    assert task_ids[0] == task_ids[1]
