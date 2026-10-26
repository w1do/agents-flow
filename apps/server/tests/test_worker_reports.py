"""Отчёты через HTTP с настоящим Postgres: атомарность, авторизация и повторы."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from catalog import DEMO, seed_workspaces
from harness_server.db.models import Checkpoint, Task, TaskEvent, TaskToken
from sqlalchemy import func, select
from worker_api_support import AUTH, Factory, app_client, claim_task, queued_task

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("events", {"text": "progress"}),
        ("status", {"text": "tests", "status": "testing"}),
        ("checkpoints", {"summary": "saved", "files": ["a.py"], "status": "active"}),
        ("result", {"text": "done", "branch": "task/test", "tests_state": "no_tests"}),
    ],
)
async def test_reports_are_idempotent_and_require_own_task_token(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
    endpoint: str,
    payload: dict[str, object],
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    task = await queued_task(committed_session_factory)
    other = await queued_task(committed_session_factory)
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        claimed = (await claim_task(client)).json()
        headers = {**AUTH, "X-Task-Token": claimed["task_token"]}
        url = f"/worker/tasks/{task.id}/{endpoint}"
        body = {"external_key": "one", **payload}
        wrong = await client.post(
            f"/worker/tasks/{other.id}/{endpoint}", headers=headers, json=body
        )
        assert wrong.status_code == 401
        responses = await asyncio.gather(
            *(client.post(url, headers=headers, json=body) for _ in range(2))
        )
        assert all(r.status_code == 200 for r in responses)
        assert responses[0].json() == responses[1].json()
        assert (await client.post(url, headers=AUTH, json=body)).status_code == 422
    async with committed_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(TaskEvent)
            .where(TaskEvent.task_id == task.id, TaskEvent.external_key.is_not(None))
        )
        assert count == 1
        if endpoint == "checkpoints":
            assert await session.scalar(select(func.count()).select_from(Checkpoint)) == 1
        if endpoint == "result":
            stored = await session.get(Task, task.id)
            assert stored is not None and stored.result == "done" and stored.branch == "task/test"
            assert stored.tests_state == "no_tests"


async def test_invalid_transition_and_expired_or_revoked_token_do_not_write(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    task = await queued_task(committed_session_factory)
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        claimed = (await claim_task(client)).json()
        headers = {**AUTH, "X-Task-Token": claimed["task_token"]}
        url = f"/worker/tasks/{task.id}/status"
        body = {"external_key": "bad", "status": "merged", "text": "no"}
        assert (await client.post(url, headers=headers, json=body)).status_code == 409
        for revoked in (False, True):
            async with committed_session_factory() as session:
                token = (await session.scalars(select(TaskToken))).one()
                token.expires_at = datetime.now(UTC) + timedelta(minutes=10 if revoked else -1)
                token.revoked_at = datetime.now(UTC) if revoked else None
                await session.commit()
            assert (await client.post(url, headers=headers, json=body)).status_code == 401
    async with committed_session_factory() as session:
        stored = await session.get(Task, task.id)
        assert stored is not None and stored.status == "active"
        assert not (
            await session.scalars(select(TaskEvent).where(TaskEvent.external_key.is_not(None)))
        ).all()


async def test_report_redacts_secrets_before_storage(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    task = await queued_task(committed_session_factory)
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        claimed = (await claim_task(client)).json()
        token = claimed["task_token"]
        secret = valid_env["HARNESS_SECRET_KEY"]
        response = await client.post(
            f"/worker/tasks/{task.id}/result",
            headers={**AUTH, "X-Task-Token": token},
            json={"external_key": "safe", "text": f"{secret} {token}"},
        )
        assert response.status_code == 200
        assert secret not in response.text and token not in response.text
    async with committed_session_factory() as session:
        stored = await session.get(Task, task.id)
        assert stored is not None and secret not in (stored.result or "")
