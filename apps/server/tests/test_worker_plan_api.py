"""Postgres: завершение плана атомарно, повторы и чужие токены безопасны."""

import asyncio
from dataclasses import replace

import pytest
from catalog import DEMO, seed_workspaces
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.db.models import Task, TaskEvent
from harness_server.services.agent_tools import invoke
from harness_shared.planning import AgentReportIn
from harness_shared.tasks import TaskKind, TaskStatus
from planning_api_support import SECRET_KEY, seed_items
from sqlalchemy import select
from worker_api_support import AUTH, Factory, app_client, claim_task, queued_task

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_plan_rejection_is_atomic_and_idempotent(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    factory = committed_session_factory
    await seed_workspaces(factory, DEMO)
    plan = await queued_task(factory, kind=TaskKind.PLAN)
    unrelated = await queued_task(factory)
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        claim = (await claim_task(client, "plan")).json()
        token = claim["task_token"]
        await seed_items(factory, token, 3)
        url = f"/worker/tasks/{plan.id}/plan"
        headers = {**AUTH, "X-Task-Token": token}
        state = await client.post(f"{url}/state", headers=headers)
        assert state.status_code == 200 and len(state.json()["children"]) == 3
        assert (
            await client.post(
                f"{url}/state",
                headers={**AUTH, "X-Task-Token": "wrong"},
            )
        ).status_code == 401
        secret = valid_env["HARNESS_SECRET_KEY"]
        body = {"external_key": "failure", "status": "error", "text": f"ошибка {secret}"}
        responses = await asyncio.gather(
            *[client.post(f"{url}/finish", headers=headers, json=body) for _ in range(2)]
        )
        assert responses[0].status_code == responses[1].status_code == 200
        assert responses[0].json() == responses[1].json()
        assert secret not in responses[0].text
    async with factory() as session:
        stored = await session.get(Task, plan.id)
        assert stored is not None and stored.status == "error"
        children = (await session.scalars(select(Task).where(Task.parent_id == plan.id))).all()
        assert len(children) == 3 and all(child.status == "trash" for child in children)
        other = await session.get(Task, unrelated.id)
        assert other is not None and other.status == "backlog"
        events = (
            await session.scalars(
                select(TaskEvent).where(
                    TaskEvent.task_id == plan.id,
                    TaskEvent.status == "error",
                )
            )
        ).all()
        assert len(events) == 1


@pytest.mark.parametrize("child_count", [1, 3])
async def test_implementations_wait_until_parent_ready(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
    child_count: int,
) -> None:
    factory = committed_session_factory
    await seed_workspaces(factory, DEMO)
    plan = await queued_task(factory, kind=TaskKind.PLAN)
    async with app_client(monkeypatch, migrated_database_url) as (app, client):
        telegram = FakeTelegramClient()
        app.state.bot = replace(app.state.bot, telegram=telegram)
        token = (await claim_task(client, "plan")).json()["task_token"]
        await seed_items(factory, token, child_count)
        assert (await claim_task(client)).json() is None
        headers = {**AUTH, "X-Task-Token": token}
        body = {
            "external_key": "ready",
            "status": "ready",
            "text": "готово",
            "branch": f"task/{plan.id}",
        }
        url = f"/worker/tasks/{plan.id}/plan/finish"
        assert (await client.post(url, headers=headers, json=body)).status_code == 409
        async with factory() as session:
            await invoke(
                session,
                token,
                SECRET_KEY,
                "report_task",
                AgentReportIn(status="completed", text="done"),
                (),
            )
        responses = await asyncio.gather(
            *[client.post(url, headers=headers, json=body) for _ in range(2)]
        )
        assert all(response.status_code == 200 for response in responses)
        assert (await client.post(url, headers=headers, json=body)).status_code == 200
        assert len(telegram.sent) == 1 and not telegram.edits
        assert f"спецификация готова, задач: {child_count}" in telegram.sent[0].text
        for i in range(1, child_count + 1):
            assert f"Часть {i}" in telegram.sent[0].text
        assert (await claim_task(client)).json()["task"]["parent_id"] == str(plan.id)
    async with factory() as session:
        stored = await session.get(Task, plan.id)
        assert stored is not None and stored.branch == f"task/{plan.id}"


async def test_rejection_rolls_back_if_a_child_is_already_active(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    factory = committed_session_factory
    await seed_workspaces(factory, DEMO)
    plan = await queued_task(factory, kind=TaskKind.PLAN)
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        token = (await claim_task(client, "plan")).json()["task_token"]
        await seed_items(factory, token, 2)
        async with factory() as session:
            children = list(
                await session.scalars(
                    select(Task).where(Task.parent_id == plan.id).order_by(Task.id),
                )
            )
            children[-1].status = TaskStatus.ACTIVE
            await session.commit()
        response = await client.post(
            f"/worker/tasks/{plan.id}/plan/finish",
            headers={**AUTH, "X-Task-Token": token},
            json={"external_key": "reject", "status": "error", "text": "отказ"},
        )
        assert response.status_code == 409
    async with factory() as session:
        stored = await session.get(Task, plan.id)
        assert stored is not None and stored.status == "planning"
        states = list(await session.scalars(select(Task.status).where(Task.parent_id == plan.id)))
        assert sorted(states) == ["active", "backlog"]
