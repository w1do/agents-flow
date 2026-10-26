"""HTTP-вход /tasks: авторизация fail-closed, создание задачи и лента (сценарии task-lifecycle)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest
from asgi_lifespan import LifespanManager
from catalog import DEMO, seed_workspaces
from fastapi import FastAPI
from harness_server.app import create_app
from harness_server.config import load_config
from harness_server.db.ids import uuid7
from harness_server.db.models import Task
from harness_server.services.tasks import change_status
from harness_server.settings import load_settings
from harness_shared.tasks import TaskEventSource, TaskStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

TOKEN = "test-admin-token-0123456789abcdef01"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

Factory = async_sessionmaker[AsyncSession]


@asynccontextmanager
async def _app_client(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    *,
    admin_token: str | None = TOKEN,
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """Приложение с настоящей БД и заданным HARNESS_ADMIN_TOKEN (None — переменная не задана)."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    if admin_token is None:
        monkeypatch.delenv("HARNESS_ADMIN_TOKEN", raising=False)
    else:
        monkeypatch.setenv("HARNESS_ADMIN_TOKEN", admin_token)
    settings = load_settings()
    app = create_app(settings, load_config(settings.harness_config))

    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield app, client


async def test_post_task_creates_plan_task(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.post("/tasks", json={"text": "новая идея"}, headers=AUTH)

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "plan"
    assert body["status"] == "new"
    assert body["source"] == "api"
    assert body["workspace_id"] is None


async def test_post_task_with_known_workspace(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)
    workspace_id = DEMO.id

    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.post(
            "/tasks", json={"text": "в проект", "workspace_id": workspace_id}, headers=AUTH
        )

    assert response.status_code == 201
    assert response.json()["workspace_id"] == workspace_id


async def test_post_task_unknown_workspace_422(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.post(
            "/tasks", json={"text": "в никуда", "workspace_id": "missing"}, headers=AUTH
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "unknown_workspace"


async def test_post_task_empty_text_422(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.post("/tasks", json={"text": "   "}, headers=AUTH)

    assert response.status_code == 422


async def test_post_task_without_token_401_creates_nothing(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.post("/tasks", json={"text": "без токена"})

    assert response.status_code == 401
    async with committed_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Task))
    assert count == 0


async def test_get_task_returns_events(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (app, client):
        created = await client.post("/tasks", json={"text": "с лентой"}, headers=AUTH)
        task_id = created.json()["id"]
        session_factory: Factory = app.state.session_factory
        async with session_factory() as session:
            await change_status(
                session,
                task_id=UUID(task_id),
                to_status=TaskStatus.CHOOSING,
                source=TaskEventSource.API,
            )

        response = await client.get(f"/tasks/{task_id}", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "choosing"
    assert len(body["events"]) == 1
    assert body["events"][0]["status"] == "choosing"


async def test_get_unknown_task_404(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.get(f"/tasks/{uuid7()}", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["detail"] == "not_found"


async def test_get_task_without_token_401(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        created = await client.post("/tasks", json={"text": "скрытая"}, headers=AUTH)
        existing = await client.get(f"/tasks/{created.json()['id']}")
        missing = await client.get(f"/tasks/{uuid7()}")

    # Существующая и несуществующая задача дают одинаковый ответ: существование не раскрывается.
    for response in (existing, missing):
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json() == {"detail": "unauthorized"}


async def test_wrong_token_401(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.post(
            "/tasks", json={"text": "чужой токен"}, headers={"Authorization": "Bearer wrong-token"}
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}


async def test_non_bearer_scheme_401(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.get(
            f"/tasks/{uuid7()}", headers={"Authorization": f"Basic {TOKEN}"}
        )

    assert response.status_code == 401


async def test_admin_token_not_configured_401(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url, admin_token=None) as (_, client):
        response = await client.post("/tasks", json={"text": "нет токена"}, headers=AUTH)

    # Fail-closed: даже правильный на вид bearer не пускает, если токен на сервере не задан.
    assert response.status_code == 401


async def test_invalid_id_without_token_401(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _app_client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.get("/tasks/not-a-uuid")

    assert response.status_code == 401
