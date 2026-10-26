"""Официальный MCP-клиент: авторизация, идемпотентность, роли и изоляция."""

from datetime import UTC, datetime, timedelta

import pytest
from catalog import DEMO, SHOP, seed_workspaces
from harness_server.db.models import SpecItem, Task, TaskToken
from harness_server.services.tasks import create_task
from harness_shared.tasks import TaskKind, TaskSource
from planning_api_support import agent_session, payload
from sqlalchemy import select
from worker_api_support import Factory, app_client, claim_task, queued_task

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_planner_tools_sync_create_report_and_isolate(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    factory = committed_session_factory
    await seed_workspaces(factory, DEMO, SHOP)
    plan = await queued_task(factory, kind=TaskKind.PLAN)
    async with factory() as session:
        await create_task(
            session,
            kind=TaskKind.PLAN,
            text="Чужой проект",
            source=TaskSource.API,
            known_workspace_ids=["shop"],
            workspace_id="shop",
        )
    async with app_client(monkeypatch, migrated_database_url) as (app, client):
        claim = (await claim_task(client, "plan")).json()
        token = claim["task_token"]
        async with agent_session(app, token) as agent:
            tools = await agent.list_tools()
            assert {t.name for t in tools.tools} == {
                "sync_spec",
                "create_task",
                "report_task",
                "list_tasks",
            }
            visible = payload(await agent.call_tool("list_tasks", {}))
            assert isinstance(visible, list) and visible
            assert all(row["workspace_id"] == "demo" for row in visible)
            sync = {
                "change_id": "add-export",
                "items": [
                    {"key": "add-export#1", "text": "Экспорт CSV", "status": "pending"},
                ],
            }
            first = payload(await agent.call_tool("sync_spec", sync))
            assert payload(await agent.call_tool("sync_spec", sync)) == first
            create = {"text": "Экспорт CSV", "spec_item_key": "add-export#1"}
            child = payload(await agent.call_tool("create_task", create))
            assert payload(await agent.call_tool("create_task", create)) == child
            result = await agent.call_tool(
                "create_task",
                {
                    "text": "Чужой пункт",
                    "spec_item_key": "foreign-change#1",
                },
            )
            assert result.is_error
            unsafe = valid_env["HARNESS_SECRET_KEY"]
            report = payload(
                await agent.call_tool(
                    "report_task",
                    {
                        "status": "completed",
                        "text": f"готово {unsafe} {token}",
                    },
                )
            )
            assert unsafe not in str(report) and token not in str(report)
            assert (await agent.call_tool("create_task", create)).is_error
        async with factory() as session:
            assert len((await session.scalars(select(SpecItem))).all()) == 1
            children = (await session.scalars(select(Task).where(Task.parent_id == plan.id))).all()
            assert len(children) == 1 and children[0].status == "backlog"
            assert children[0].workspace_id == "demo" and children[0].spec_item_id is not None
            stored = await session.get(Task, plan.id)
            assert stored is not None and stored.status == "planning"


async def test_mcp_rejects_missing_expired_revoked_and_implementer_writes(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    factory = committed_session_factory
    await seed_workspaces(factory, DEMO)
    await queued_task(factory)
    async with app_client(monkeypatch, migrated_database_url) as (app, client):
        claim = (await claim_task(client)).json()
        assert (await client.post("/mcp")).status_code == 401
        assert (
            await client.post("/mcp", headers={"Authorization": "Bearer wrong"})
        ).status_code == 401
        async with agent_session(app, claim["task_token"]) as agent:
            assert (
                await agent.call_tool(
                    "sync_spec",
                    {
                        "change_id": "other",
                        "items": [
                            {"key": "other#1", "text": "other", "status": "pending"},
                        ],
                    },
                )
            ).is_error
        for field in ("expires_at", "revoked_at"):
            async with factory() as session:
                row = (await session.scalars(select(TaskToken))).one()
                row.expires_at = datetime.now(UTC) + timedelta(minutes=10)
                setattr(row, field, datetime(2000, 1, 1, tzinfo=UTC))
                await session.commit()
            response = await client.post(
                "/mcp",
                headers={
                    "Authorization": f"Bearer {claim['task_token']}",
                },
            )
            assert response.status_code == 401 and claim["task_token"] not in response.text
