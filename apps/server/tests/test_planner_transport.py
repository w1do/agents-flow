"""Проверка MCP-транспорта SDK без подключения БД; правила доступа отдельно в Postgres."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from harness_server.db.models import Task
from harness_server.domain.errors import WorkerUnauthorized
from harness_server.mcp.server import PlannerMCP
from harness_shared.planning import SpecSyncIn
from mcp.types import TextContent
from planning_api_support import agent_session, payload
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.routing import Route

TOKEN = "transport-test-token"


async def test_official_client_initializes_lists_calls_and_hides_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = async_sessionmaker(create_async_engine("postgresql+asyncpg://u:p@127.0.0.1:1/db"))

    async def authorized(session: AsyncSession, token: str, secret_key: str) -> Task:
        if token != TOKEN:
            raise WorkerUnauthorized()
        return Task()

    async def invoked(
        session: AsyncSession,
        token: str,
        secret_key: str,
        name: str,
        body: BaseModel,
        secrets: Sequence[str],
    ) -> object:
        assert name == "sync_spec" and isinstance(body, SpecSyncIn)
        return [body]

    monkeypatch.setattr("harness_server.mcp.server.agent_task", authorized)
    monkeypatch.setattr("harness_server.mcp.server.invoke", invoked)
    mcp = PlannerMCP(lambda: factory, "test-key", ())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with mcp.manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.router.routes.append(Route("/mcp", endpoint=mcp))
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            assert (await client.post("/mcp")).status_code == 401
            assert (
                await client.post(
                    "/mcp",
                    headers={
                        "Authorization": "Bearer wrong",
                    },
                )
            ).status_code == 401
        async with agent_session(app, TOKEN) as agent:
            assert len((await agent.list_tools()).tools) == 4
            body = {
                "change_id": "export",
                "items": [
                    {"key": "export#1", "text": "CSV", "status": "pending"},
                ],
            }
            assert payload(await agent.call_tool("sync_spec", body)) == [body]
            invalid = await agent.call_tool("create_task", {"text": TOKEN})
            assert invalid.is_error
            assert all(
                TOKEN not in block.text
                for block in invalid.content
                if isinstance(block, TextContent)
            )
