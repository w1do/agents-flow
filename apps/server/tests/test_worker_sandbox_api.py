"""D-41 через HTTP: сведения сервера, защита запуска и восстановление очистки."""

import asyncio
from datetime import UTC, datetime

import pytest
from catalog import DEMO, seed_workspaces
from harness_server.db.models import Sandbox, TaskToken
from harness_server.services.sandboxes import has_live_task_token
from sqlalchemy import select
from worker_api_support import AUTH, Factory, app_client, queued_task

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_recovery_retains_agent_token_and_records_start_once(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    task = await queued_task(committed_session_factory)
    async with app_client(monkeypatch, migrated_database_url) as (app, client):
        provider = app.state.config.sandbox.provider_id
        body = {"provider_id": provider}
        claim = (
            await client.post(
                "/worker/tasks/claim",
                headers=AUTH,
                json={
                    "kind": "implement",
                    **body,
                },
            )
        ).json()
        headers = {**AUTH, "X-Task-Token": claim["task_token"]}
        base = f"/worker/tasks/{task.id}/sandbox"
        assert (await client.post(f"{base}/reserve", headers=headers, json=body)).status_code == 200
        start = {**body, "external_key": "first", "started_at": datetime.now(UTC).isoformat()}
        first = await client.post(f"{base}/start", headers=headers, json=start)
        assert first.status_code == 200 and first.json()["launch"]
        again = await client.post(f"{base}/start", headers=headers, json=start)
        assert again.json() == first.json()
        different = await client.post(
            f"{base}/start", headers=headers, json={**start, "external_key": "second"}
        )
        assert not different.json()["launch"]
        assert (
            await client.post(f"{base}/pid", headers=headers, json={**body, "pid": 4242})
        ).status_code == 200
        assert (
            await client.post(f"{base}/pid", headers=headers, json={**body, "pid": 4243})
        ).status_code == 409
        recovered = await client.post("/worker/sandbox/recover", headers=AUTH, json=body)
        assert recovered.status_code == 200
        data = recovered.json()
        assert data["sandbox"]["pid"] == 4242
        assert data["sandbox"]["started_at"] == first.json()["state"]["started_at"]
        assert data["claim"]["task"]["id"] == str(task.id)
        assert data["claim"]["task_token"] != claim["task_token"]
    async with committed_session_factory() as session:
        tokens = (await session.scalars(select(TaskToken))).all()
        assert len(tokens) == 2 and all(t.revoked_at is None for t in tokens)
        assert await has_live_task_token(session, task.id)


@pytest.mark.parametrize("success", [True, False])
async def test_cleanup_revokes_before_commands_and_retains_failed_reservation(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
    success: bool,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    task = await queued_task(committed_session_factory)
    other = await queued_task(committed_session_factory)
    async with app_client(monkeypatch, migrated_database_url) as (app, client):
        body = {"provider_id": app.state.config.sandbox.provider_id}
        claim = (
            await client.post(
                "/worker/tasks/claim", headers=AUTH, json={"kind": "implement", **body}
            )
        ).json()
        headers = {**AUTH, "X-Task-Token": claim["task_token"]}
        base = f"/worker/tasks/{task.id}/sandbox"
        wrong = await client.post(
            f"/worker/tasks/{other.id}/sandbox/cleanup", headers=headers, json=body
        )
        assert wrong.status_code == 409
        premature = await client.post(
            f"{base}/release", headers=headers, json={**body, "success": True}
        )
        assert premature.status_code == 409
        assert (await client.post(f"{base}/cleanup", headers=headers, json=body)).status_code == 200
        async with committed_session_factory() as session:
            assert all(
                t.revoked_at is not None for t in (await session.scalars(select(TaskToken))).all()
            )
        assert (await client.post(f"{base}/cleanup", headers=AUTH, json=body)).status_code == 200
        recovery = (await client.post("/worker/sandbox/recover", headers=AUTH, json=body)).json()
        assert recovery["sandbox"]["cleanup_started"]
        assert recovery["claim"]["task_token"] == ""
        assert (
            await client.post(f"{base}/release", headers=AUTH, json={**body, "success": success})
        ).status_code == 204
        if success:
            assert (
                await client.post(f"{base}/release", headers=AUTH, json={**body, "success": True})
            ).status_code == 204
    async with committed_session_factory() as session:
        row = (await session.scalars(select(Sandbox))).one()
        assert row.status == ("paused" if success else "error")
        assert row.current_task_id == (None if success else task.id)


async def test_concurrent_workers_register_and_claim_one_sandbox_once(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    await queued_task(committed_session_factory)
    await queued_task(committed_session_factory)
    async with app_client(monkeypatch, migrated_database_url) as (app, client):
        body = {"kind": "implement", "provider_id": app.state.config.sandbox.provider_id}
        responses = await asyncio.gather(
            *(client.post("/worker/tasks/claim", headers=AUTH, json=body) for _ in range(2))
        )
        assert all(r.status_code == 200 for r in responses)
        assert len([r for r in responses if r.json() is not None]) == 1
    async with committed_session_factory() as session:
        assert len((await session.scalars(select(Sandbox))).all()) == 1
        assert len((await session.scalars(select(TaskToken))).all()) == 1
