"""Захват через HTTP: конкуренция реальных транзакций и фильтрация очереди."""

import asyncio
from datetime import UTC, datetime

import pytest
from catalog import DEMO, DEMO_KEY_REF, seed_workspaces
from harness_server.db.models import Task, TaskToken
from harness_server.security.tokens import hash_token
from harness_server.services.projects import disable_project
from harness_shared.tasks import TaskKind, TaskStatus
from sqlalchemy import select
from worker_api_support import AUTH, WORKER, Factory, app_client, claim_task, queued_task

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize("kind", [TaskKind.PLAN, TaskKind.IMPLEMENT])
async def test_one_task_is_claimed_only_once(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
    kind: TaskKind,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    task = await queued_task(committed_session_factory, kind=kind)
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        responses = await asyncio.gather(*(claim_task(client, kind.value) for _ in range(2)))
        assert all(response.status_code == 200 for response in responses)
        claims = [response.json() for response in responses if response.json() is not None]
        assert len(claims) == 1
        assert (await claim_task(client, kind.value)).json() is None
    claim = claims[0]
    assert claim["task"]["id"] == str(task.id)
    assert claim["role"] == ("planner" if kind == TaskKind.PLAN else "implementer")
    async with committed_session_factory() as session:
        token = (await session.scalars(select(TaskToken))).one()
        assert token.token_hash == hash_token(claim["task_token"], valid_env["HARNESS_SECRET_KEY"])
        assert token.expires_at > datetime.now(UTC)
        assert token.revoked_at is None


async def test_disabled_project_stays_in_queue(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    task = await queued_task(committed_session_factory)
    async with committed_session_factory() as session:
        await disable_project(session, DEMO.id)
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        assert (await claim_task(client)).json() is None
    async with committed_session_factory() as session:
        stored = await session.get(Task, task.id)
        assert stored is not None and stored.status == TaskStatus.BACKLOG
        assert not (await session.scalars(select(TaskToken))).all()


async def test_claim_contains_reference_and_redacts_secrets(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    oauth = "sk-ant-test-subscription-0123456789abcdef"
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", oauth)
    text = f"key {WORKER} subscription {oauth} db {migrated_database_url}"
    await queued_task(committed_session_factory, text=text)
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await claim_task(client)
    assert response.status_code == 200
    assert response.json()["project"]["repo"]["access_ref"] == DEMO_KEY_REF
    for secret in (WORKER, oauth, migrated_database_url, valid_env["HARNESS_SECRET_KEY"]):
        assert secret not in response.text
    assert "[REDACTED]" in response.text


async def test_empty_queue_and_invalid_claim(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await claim_task(client)
        assert response.status_code == 200 and response.json() is None
        invalid = await client.post("/worker/tasks/claim", json={"kind": "check"}, headers=AUTH)
        assert invalid.status_code == 422
