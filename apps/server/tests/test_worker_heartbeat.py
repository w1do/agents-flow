"""Сервер определяет stalled; heartbeat и повторная проверка не создают дублей."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from catalog import DEMO, seed_workspaces
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.db.models import Task, TaskEvent
from harness_server.services.context import BotContext
from harness_server.services.status_report import build_status_report
from harness_server.services.worker_heartbeat import expire_heartbeats
from sqlalchemy import select
from worker_api_support import AUTH, Factory, app_client, claim_task, queued_task

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize("kind", ["plan", "implement"])
async def test_only_missed_heartbeat_becomes_stalled(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
    kind: str,
    make_bot_context: Callable[..., BotContext],
) -> None:
    from harness_shared.tasks import TaskKind

    await seed_workspaces(committed_session_factory, DEMO)
    task = await queued_task(committed_session_factory, kind=TaskKind(kind))
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        claim = (await claim_task(client, kind)).json()
        url = f"/worker/tasks/{task.id}/heartbeat"
        headers = {**AUTH, "X-Task-Token": claim["task_token"]}
        assert (
            await client.post(url, headers={**AUTH, "X-Task-Token": "wrong"})
        ).status_code == 401
        assert (await client.post(url, headers=headers)).status_code == 204
        async with committed_session_factory() as session:
            assert await expire_heartbeats(session, 120) == 0
            assert (
                await expire_heartbeats(session, 120, now=datetime.now(UTC) + timedelta(minutes=3))
                == 1
            )
            assert (
                await expire_heartbeats(session, 120, now=datetime.now(UTC) + timedelta(minutes=4))
                == 0
            )
    async with committed_session_factory() as session:
        stored = await session.get(Task, task.id)
        assert stored is not None and stored.status == "stalled"
        events = (
            await session.scalars(
                select(TaskEvent).where(TaskEvent.task_id == task.id, TaskEvent.status == "stalled")
            )
        ).all()
        assert len(events) == 1

    report = await build_status_report(
        make_bot_context(committed_session_factory, telegram=FakeTelegramClient())
    )
    assert "stalled" in report
