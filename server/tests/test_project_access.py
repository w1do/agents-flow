from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends

from app.models import Agent
from app.repositories import AgentRepository, ProjectRepository
from app.services.agent_auth import generate_agent_token
from app.services.projects import get_project


@pytest.fixture
def agent_access(app, session, project):
    from app.api.deps import Database, ensure_agent_access, ensure_project_access, require_agent

    token, token_hash = generate_agent_token()
    agents = AgentRepository(session)
    agent = agents.create(project_id=project.id, name="Agent", agent_token_hash=token_hash,
                          repository_path_hint="", git_remote="")
    colleague = agents.create(project_id=project.id, name="Colleague", agent_token_hash="hidden",
                              repository_path_hint="", git_remote="")
    other = ProjectRepository(session).create(name="Other")
    foreign = agents.create(project_id=other.id, name="Foreign", agent_token_hash="foreign",
                            repository_path_hint="", git_remote="")

    @app.get("/test/projects/{project_id}")
    async def project_route(project_id: UUID, actor: Annotated[Agent, Depends(require_agent)],
                            database: Database):
        target = get_project(database, project_id)
        ensure_project_access(actor, target.id)
        return {"id": str(target.id)}

    @app.get("/test/agents/{agent_id}")
    async def agent_route(agent_id: UUID, actor: Annotated[Agent, Depends(require_agent)],
                          database: Database):
        target = AgentRepository(database).get(agent_id)
        ensure_agent_access(actor, target)
        return {"id": str(target.id)}

    return agent, colleague, foreign, {"Authorization": f"Bearer {token}"}


async def test_own_project_and_agent(client, agent_access):
    agent, _, _, headers = agent_access
    for path in [f"/test/projects/{agent.project_id}", f"/test/agents/{agent.id}"]:
        response = await client.get(path, headers=headers)
        assert response.status_code == 200


async def test_foreign_project_and_agent(client, agent_access):
    _, colleague, foreign, headers = agent_access
    for path in [f"/test/projects/{foreign.project_id}", f"/test/agents/{foreign.id}",
                 f"/test/agents/{colleague.id}"]:
        response = await client.get(path, headers=headers)
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("kind", ["projects", "agents"])
async def test_missing_target(client, agent_access, kind):
    response = await client.get(f"/test/{kind}/{uuid4()}", headers=agent_access[-1])
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Basic invalid"])
async def test_agent_requires_valid_token(client, agent_access, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = await client.get(f"/test/agents/{agent_access[0].id}", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_agent_token_has_no_admin_access(client, agent_access):
    response = await client.get("/api/v1/projects", headers=agent_access[-1])
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_admin_token_has_no_agent_access(client, agent_access, admin_headers):
    response = await client.get(f"/test/agents/{agent_access[0].id}", headers=admin_headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_missing_agent_object():
    from fastapi import HTTPException

    from app.api.deps import ensure_project_access

    with pytest.raises(HTTPException) as error:
        ensure_project_access(None, uuid4())
    assert error.value.status_code == 404


def test_missing_project_object(agent_access):
    from fastapi import HTTPException

    from app.api.deps import ensure_project_access

    with pytest.raises(HTTPException) as error:
        ensure_project_access(agent_access[0], uuid4())
    assert error.value.status_code == 404
