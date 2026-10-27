from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Project, ProjectInitToken
from app.repositories import AgentRepository, ProjectRepository, TaskRepository
from app.services.init_tokens import consume_init_token, issue_init_token


async def test_create_and_get_project(client, admin_headers, session):
    body = {"name": "Demo", "description": "Description", "telegram_chat_id": "-100123"}
    response = await client.post("/api/v1/projects", json=body, headers=admin_headers)
    assert response.status_code == 201
    card = response.json()
    assert all(card[key] == value for key, value in body.items())
    assert card["active_task_count"] == 0
    assert card["agents"] == []
    assert "telegram_chat_id" in card and "updated_at" in card
    assert card["init_code_expires_at"] is None
    assert "project_token_hash" not in card
    fetched = await client.get(f"/api/v1/projects/{card['id']}", headers=admin_headers)
    assert fetched.status_code == 200
    assert fetched.json() == card
    session.expunge_all()
    assert session.scalar(select(Project)).name == "Demo"


async def test_minimal_project(client, admin_headers):
    response = await client.post("/api/v1/projects", json={"name": "Minimal"}, headers=admin_headers)
    assert response.status_code == 201
    assert response.json()["description"] is None
    assert response.json()["telegram_chat_id"] is None


async def test_agent_list_is_scoped_to_project(client, admin_headers, session, project):
    other = ProjectRepository(session).create(name="Other")
    AgentRepository(session).create(project_id=other.id, name="Foreign", agent_token_hash="hash",
                                    repository_path_hint="", git_remote="origin")
    response = await client.get(f"/api/v1/projects/{project.id}/agents", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_list_counts(client, admin_headers, session, project):
    other = ProjectRepository(session).create(name="Other")
    for status in ["new", "choosing", "planning", "backlog", "active", "testing", "ready",
                   "merged", "error", "stalled", "paused", "trash"]:
        TaskRepository(session).create(project_id=project.id, title=status, description="",
                                       source_type="api", source_text="", status=status)
    TaskRepository(session).create(project_id=other.id, title="Other", description="",
                                   source_type="api", source_text="", status="active")
    for index in range(2):
        AgentRepository(session).create(project_id=project.id, name=str(index),
                                        agent_token_hash="hash", repository_path_hint="", git_remote="")
    response = await client.get("/api/v1/projects", headers=admin_headers)
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    assert rows[str(project.id)]["active_task_count"] == 4
    assert len(rows[str(project.id)]["agents"]) == 2
    assert rows[str(other.id)]["active_task_count"] == 1
    assert rows[str(other.id)]["agents"] == []
    assert rows[str(project.id)]["init_code_expires_at"] is None
    assert set(rows[str(project.id)]) == {
        "id", "name", "description", "active_task_count", "agents", "telegram_chat_id",
        "created_at", "updated_at", "init_code_expires_at",
    }


async def test_init_code_is_returned_only_once(client, admin_headers, project, session):
    response = await client.post(f"/api/v1/projects/{project.id}/init-tokens", headers=admin_headers)
    assert response.status_code == 201
    issued = response.json()
    assert set(issued) == {"code", "expires_at"}
    card = await client.get(f"/api/v1/projects/{project.id}", headers=admin_headers)
    assert card.json()["init_code_expires_at"] == issued["expires_at"]
    assert issued["code"] not in card.text
    assert "code" not in card.json() and "init_code" not in card.json()
    consume_init_token(session, issued["code"], project.id)
    card = await client.get(f"/api/v1/projects/{project.id}", headers=admin_headers)
    assert card.json()["init_code_expires_at"] is None


async def test_expired_init_code_not_shown(client, admin_headers, project, session):
    issue_init_token(session, project.id)
    token = session.scalar(select(ProjectInitToken))
    token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.flush()
    response = await client.get(f"/api/v1/projects/{project.id}", headers=admin_headers)
    assert response.json()["init_code_expires_at"] is None


@pytest.mark.parametrize("stored,age,expected", [
    ("online", None, "offline"), ("busy", 121, "offline"), ("online", 121, "offline"),
    ("online", 1, "online"), ("busy", 1, "busy"), ("offline", 1, "offline"),
])
async def test_agent_heartbeat_status(client, admin_headers, session, project, stored, age, expected):
    heartbeat = datetime.now(timezone.utc) - timedelta(seconds=age) if age is not None else None
    AgentRepository(session).create(
        project_id=project.id, name="Agent", agent_token_hash="hidden", status=stored,
        last_heartbeat_at=heartbeat, repository_path_hint="/repo", git_remote="origin",
    )
    response = await client.get(f"/api/v1/projects/{project.id}/agents", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()[0]["status"] == expected
    assert set(response.json()[0]) == {
        "id", "project_id", "name", "status", "last_heartbeat_at", "git_remote",
        "repository_path_hint", "created_at", "updated_at",
    }
    assert "hidden" not in response.text


@pytest.mark.parametrize("method,suffix", [("get", ""), ("get", "/agents"), ("post", "/init-tokens")])
async def test_unknown_project(client, admin_headers, method, suffix):
    response = await getattr(client, method)(f"/api/v1/projects/{uuid4()}{suffix}", headers=admin_headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("method,path", [
    ("get", "/projects"), ("post", "/projects"), ("get", f"/projects/{uuid4()}"),
    ("get", f"/projects/{uuid4()}/agents"), ("post", f"/projects/{uuid4()}/init-tokens"),
])
async def test_all_project_routes_require_admin(client, method, path):
    response = await getattr(client, method)(f"/api/v1{path}")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_project_create_rejects_unknown_field(client, admin_headers):
    response = await client.post("/api/v1/projects", headers=admin_headers,
                                 json={"name": "Demo", "extra": True})
    assert response.status_code == 422


async def test_project_name_must_not_be_blank(client, admin_headers):
    response = await client.post("/api/v1/projects", headers=admin_headers, json={"name": "   "})
    assert response.status_code == 422


