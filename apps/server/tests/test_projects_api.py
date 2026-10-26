"""HTTP-вход каталога проектов: консоль и выдача настроек под операторским токеном (D-65, D-23)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from asgi_lifespan import LifespanManager
from catalog import DEMO, seed_workspaces
from fastapi import FastAPI
from harness_server.app import create_app
from harness_server.settings import load_settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

TOKEN = "test-admin-token-0123456789abcdef01"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PLAIN_KEY = "github_pat_plain_must_not_appear_0123"
Factory = async_sessionmaker[AsyncSession]


@asynccontextmanager
async def _client(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("HARNESS_ADMIN_TOKEN", TOKEN)
    settings = load_settings()
    from harness_server.config import load_config

    app = create_app(settings, load_config(settings.harness_config))
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield app, client


def _new_project(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "shop",
        "name": "Магазин",
        "voice_aliases": ["магазин"],
        "repo": {
            "provider": "github",
            "project": "owner/shop",
            "access_ref": "vault:shop/github/main",
        },
        "agent": "claude-code",
        "agent_max_turns": 50,
    }
    body.update(overrides)
    return body


async def test_create_list_get_update_disable_round_trip(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    async with _client(monkeypatch, migrated_database_url) as (_, client):
        created = await client.post("/api/console/projects", json=_new_project(), headers=AUTH)
        listed = await client.get("/api/console/projects", headers=AUTH)
        fetched = await client.get("/api/console/projects/shop", headers=AUTH)
        updated = await client.patch(
            "/api/console/projects/shop", json={"test_command": "pytest"}, headers=AUTH
        )
        disabled = await client.post("/api/console/projects/shop/disable", headers=AUTH)

    assert created.status_code == 201, created.text
    assert created.json()["status"] == "active"
    assert created.json()["repo"]["access_ref"] == "vault:shop/github/main"
    assert [item["id"] for item in listed.json()] == ["shop"]
    assert fetched.status_code == 200
    assert updated.json()["test_command"] == "pytest"
    assert disabled.json()["status"] == "disabled"


async def test_create_duplicate_id_is_409_and_keeps_project(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)

    async with _client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.post(
            "/api/console/projects", json=_new_project(id="demo", name="Подмена"), headers=AUTH
        )
        current = await client.get("/api/console/projects/demo", headers=AUTH)

    assert response.status_code == 409
    assert response.json() == {"detail": "project_conflict"}
    assert current.json()["name"] == "Демо-проект"


async def test_plain_key_in_access_ref_is_422_with_field_name_only(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
) -> None:
    body = _new_project(
        repo={"provider": "github", "project": "owner/shop", "access_ref": PLAIN_KEY}
    )

    async with _client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.post("/api/console/projects", json=body, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "invalid_project", "fields": ["repo.access_ref"]}
    assert PLAIN_KEY not in response.text


async def test_non_object_body_is_422_without_content(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
) -> None:
    async with _client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.post(
            "/api/console/projects", content=b'"just-a-string"', headers=AUTH
        )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"] == ["body"]


async def test_unknown_project_is_404_without_details(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
) -> None:
    async with _client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.get("/api/console/projects/missing", headers=AUTH)
        settings = await client.get("/api/projects/missing/settings", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"detail": "not_found"}
    assert settings.json() == {"detail": "not_found"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-token-0123456789abcdef0"}])
async def test_missing_or_wrong_token_is_401_without_details(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
    headers: dict[str, str],
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)

    async with _client(monkeypatch, migrated_database_url) as (_, client):
        responses = [
            await client.get("/api/console/projects", headers=headers),
            await client.get("/api/projects/demo/settings", headers=headers),
            await client.post("/api/console/projects", json=_new_project(), headers=headers),
        ]

    for response in responses:
        assert response.status_code == 401
        assert response.json() == {"detail": "unauthorized"}
        assert "demo" not in response.text


async def test_settings_for_operator_contain_no_key_values(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)

    async with _client(monkeypatch, migrated_database_url) as (_, client):
        response = await client.get("/api/projects/demo/settings", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["repo"]["access_ref"] == "vault:demo/gitlab/main"
    assert set(body) == {
        "id",
        "name",
        "voice_aliases",
        "repo",
        "default_branch",
        "test_command",
        "agent",
        "agent_max_turns",
    }
    assert "glpat" not in response.text


async def test_settings_of_disabled_project_is_409(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)

    async with _client(monkeypatch, migrated_database_url) as (_, client):
        await client.post("/api/console/projects/demo/disable", headers=AUTH)
        response = await client.get("/api/projects/demo/settings", headers=AUTH)

    assert response.status_code == 409
    assert response.json() == {"detail": "project_disabled"}


async def test_task_for_disabled_project_is_rejected_with_409(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
) -> None:
    await seed_workspaces(committed_session_factory, DEMO)

    async with _client(monkeypatch, migrated_database_url) as (_, client):
        await client.post("/api/console/projects/demo/disable", headers=AUTH)
        response = await client.post(
            "/tasks", json={"text": "в отключённый", "workspace_id": "demo"}, headers=AUTH
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "project_disabled"}
