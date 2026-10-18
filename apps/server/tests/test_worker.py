"""Сценарий 3.2: worker работает в цикле и завершается с кодом 0 по SIGTERM."""

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
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.config import load_config
from harness_server.db.models import TelegramUpdate
from harness_server.services.tasks import list_tasks
from harness_server.settings import load_settings
from harness_server.telegram.parse import dedup_key, dump_incoming, parse_update
from harness_server.wiring import BotAdapters
from harness_server.worker import start_worker
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_worker_stops_cleanly_on_sigterm(
    valid_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SEC", "0.2")
    # Консольный скрипт лежит рядом с интерпретатором venv; так тест не зависит от uv.
    script = Path(sys.executable).parent / "harness-server"

    process = subprocess.Popen(
        [str(script), "worker"],
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
async def test_start_worker_runs_recovery(
    valid_env: dict[str, str],
    migrated_database_url: str,
    committed_session_factory: async_sessionmaker[AsyncSession],
    telegram_update: Callable[[str], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Строка апдейта старше порога обрабатывается, когда worker стартует (stop уже установлен)."""
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
    stop = asyncio.Event()
    stop.set()

    await start_worker(settings, config, stop, adapters=BotAdapters(telegram=fake, stt=None))

    async with committed_session_factory() as session:
        tasks = await list_tasks(session)
        row = await session.get(TelegramUpdate, (kind, external_id))
    assert len(tasks) == 1
    assert row is not None
    assert row.processed_at is not None
    assert len(fake.sent) == 1
