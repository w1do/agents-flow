import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.models import Agent, AgentSkill, ProjectInitToken, TaskEvent
from app.repositories import ProjectRepository, SkillCategoryRepository, SkillRepository
from app.services.agent_auth import authenticate_agent
from app.services.init_tokens import issue_init_token


@pytest.fixture
def init_body(session, project):
    code, _ = issue_init_token(session, project.id)
    session.commit()
    return {"project_id": str(project.id), "init_code": code, "agent_name": "Worker"}


async def test_harness_init(client, session, init_body, caplog):
    category = SkillCategoryRepository(session).create(name="Development", description="Tools")
    for name, active in [("Build", True), ("Build", True), ("Archived", False)]:
        SkillRepository(session).create(category_id=category.id, name=name, description="",
                                        content="Run build", content_hash="hash", is_active=active)
    response = await client.post("/api/v1/harness/init", json=init_body)
    assert response.status_code == 201
    data = response.json()
    assert data["agent_id"] and data["agent_token"]
    assert data["poll_interval_seconds"] == 5
    assert data["lease_ttl_seconds"] == 60
    assert data["server_url"] == "http://localhost:8000"
    assert data["skills"] == []
    session.expunge_all()
    agent = session.get(Agent, UUID(data["agent_id"]))
    assert agent.status == "offline" and agent.last_heartbeat_at is None
    assert agent.repository_path_hint == agent.git_remote == ""
    assert agent.agent_token_hash == sha256(data["agent_token"].encode()).hexdigest()
    assert agent.agent_token_hash != data["agent_token"]
    assert authenticate_agent(data["agent_token"], session).id == agent.id
    assert authenticate_agent("invalid", session) is None
    assert session.scalar(select(func.count()).select_from(AgentSkill)) == 0
    assert session.scalar(select(ProjectInitToken)).used_at is not None
    assert data["agent_token"] not in caplog.text and init_body["init_code"] not in caplog.text
    assert session.scalar(select(func.count()).select_from(TaskEvent)) == 0


async def test_repository_hints(client, init_body, session):
    init_body.update(repository_path_hint="/repos/demo", git_remote="git@example.test:demo.git")
    response = await client.post("/api/v1/harness/init", json=init_body)
    assert response.status_code == 201
    assert response.json()["skills"] == []
    agent = session.scalar(select(Agent))
    assert agent.repository_path_hint == init_body["repository_path_hint"]
    assert agent.git_remote == init_body["git_remote"]


async def test_git_remote_rejects_credentials(client, init_body, session):
    init_body["git_remote"] = "https://user:secret@example.test/org/repo.git"
    response = await client.post("/api/v1/harness/init", json=init_body)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert {"loc", "msg", "type"} <= set(detail[0])
    assert detail[0]["loc"] == ["body", "git_remote"]
    assert "credentials" in detail[0]["msg"]
    assert session.scalar(select(func.count()).select_from(Agent)) == 0


@pytest.mark.parametrize("remote", [
    "https::https://user:secret@example.test/repo.git",
    "https://user:secret@example.test/repo.git",
    "https://[",
    "https://host/x\u0000", "https://host/\ud800",
    "https://host/\u200b",
])
async def test_git_remote_rejects_unsafe_syntax(client, init_body, session, remote):
    body = json.dumps(init_body | {"git_remote": remote}, ensure_ascii=True)
    response = await client.post("/api/v1/harness/init", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert session.scalar(select(func.count()).select_from(Agent)) == 0


@pytest.mark.parametrize("remote", [
    "git@github.com:org/repo.git",
    "deploy@host:repo.git",
    "https://github.com/org/repo.git",
    "ssh://git@host/repo.git",
    "ssh://git@[2001:db8::1]/repo.git",
    "ssh://[::1]/x",
])
async def test_git_remote_accepts_supported_syntax(client, init_body, remote):
    response = await client.post("/api/v1/harness/init", json=init_body | {"git_remote": remote})
    assert response.status_code == 201


async def test_harness_rejects_unknown_fields(client, init_body):
    response = await client.post("/api/v1/harness/init", json=init_body | {"extra": True})
    assert response.status_code == 422


async def test_repeated_init(client, init_body, session):
    first = await client.post("/api/v1/harness/init", json=init_body)
    assert first.status_code == 201
    for name in ["Worker", "Other"]:
        response = await client.post("/api/v1/harness/init", json=init_body | {"agent_name": name})
        assert response.status_code == 401
        assert response.json() == {"detail": "Unauthorized"}
        assert first.json()["agent_token"] not in response.text
    assert session.scalar(select(func.count()).select_from(Agent)) == 1


async def test_expired_init(client, init_body, session):
    session.scalar(select(ProjectInitToken)).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()
    response = await client.post("/api/v1/harness/init", json=init_body)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert session.scalar(select(func.count()).select_from(Agent)) == 0


async def test_foreign_project_init(client, init_body, session):
    other = ProjectRepository(session).create(name="Other")
    response = await client.post("/api/v1/harness/init", json=init_body | {"project_id": str(other.id)})
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}
    assert session.scalar(select(ProjectInitToken)).used_at is None
    assert session.scalar(select(func.count()).select_from(Agent)) == 0


async def test_name_conflict_does_not_consume_code(client, init_body, session, project):
    assert (await client.post("/api/v1/harness/init", json=init_body)).status_code == 201
    code, _ = issue_init_token(session, project.id)
    body = init_body | {"init_code": code}
    response = await client.post("/api/v1/harness/init", json=body)
    assert response.status_code == 409
    assert response.json() == {"detail": "Conflict"}
    assert (await client.post("/api/v1/harness/init", json=body | {"agent_name": "New"})).status_code == 201
    assert session.scalar(select(func.count()).select_from(Agent)) == 2


async def test_same_name_in_different_project(client, init_body, session):
    assert (await client.post("/api/v1/harness/init", json=init_body)).status_code == 201
    other = ProjectRepository(session).create(name="Other")
    code, _ = issue_init_token(session, other.id)
    response = await client.post("/api/v1/harness/init", json={"project_id": str(other.id), "init_code": code,
                                                                 "agent_name": init_body["agent_name"]})
    assert response.status_code == 201
