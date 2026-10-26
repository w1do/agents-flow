"""Помощники интеграционных проверок MCP и плана с Postgres."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
import mcp.types as types
from fastapi import FastAPI
from harness_server.services.agent_tools import invoke
from harness_shared.planning import AgentTaskIn, SpecSyncIn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from worker_api_support import Factory

SECRET_KEY = "test-secret-key-0123456789abcdef0123"


@asynccontextmanager
async def agent_session(app: FastAPI, token: str) -> AsyncIterator[ClientSession]:
    async with (
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers={"Authorization": f"Bearer {token}"},
        ) as http,
        streamable_http_client("http://test/mcp", http_client=http) as streams,
        ClientSession(*streams) as session,
    ):
        await session.initialize()
        yield session


def payload(result: types.CallToolResult) -> object:
    assert not result.is_error
    block = result.content[0]
    assert isinstance(block, types.TextContent)
    value: object = json.loads(block.text)
    return value


async def seed_items(factory: Factory, token: str, count: int = 1) -> None:
    async with factory() as session:
        await invoke(
            session,
            token,
            SECRET_KEY,
            "sync_spec",
            SpecSyncIn.model_validate(
                {
                    "change_id": "add-export",
                    "items": [
                        {"key": f"add-export#{i}", "text": f"Часть {i}", "status": "pending"}
                        for i in range(1, count + 1)
                    ],
                }
            ),
            (),
        )
    for i in range(1, count + 1):
        async with factory() as session:
            await invoke(
                session,
                token,
                SECRET_KEY,
                "create_task",
                AgentTaskIn(
                    text=f"Часть {i}",
                    spec_item_key=f"add-export#{i}",
                ),
                (),
            )
