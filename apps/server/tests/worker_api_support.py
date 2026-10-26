"""Общие HTTP-фикстуры worker API с настоящими транзакциями Postgres."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from harness_server.app import create_app
from harness_server.config import load_config
from harness_server.db.models import Task
from harness_server.services.tasks import change_status, create_task
from harness_server.settings import load_settings
from harness_shared.tasks import TaskEventSource, TaskKind, TaskSource, TaskStatus
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ADMIN = "test-admin-token-0123456789abcdef01"
WORKER = "test-worker-token-0123456789abcdef01"
AUTH = {"Authorization": f"Bearer {WORKER}"}
Factory = async_sessionmaker[AsyncSession]


@asynccontextmanager
async def app_client(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("HARNESS_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("WORKER_API_TOKEN", WORKER)
    settings = load_settings()
    app = create_app(settings, load_config(settings.harness_config))
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield app, client


async def queued_task(
    factory: Factory, *, kind: TaskKind = TaskKind.IMPLEMENT, text: str = "сделай задачу"
) -> Task:
    async with factory() as session:
        task = await create_task(
            session,
            kind=kind,
            text=text,
            source=TaskSource.API,
            known_workspace_ids=["demo"],
            workspace_id="demo",
        )
        if kind == TaskKind.PLAN:
            for target in (TaskStatus.CHOOSING, TaskStatus.PLANNING):
                await change_status(session, task.id, target, source=TaskEventSource.API)
        return task


async def claim_task(client: httpx.AsyncClient, kind: str = "implement") -> httpx.Response:
    return await client.post("/worker/tasks/claim", json={"kind": kind}, headers=AUTH)
