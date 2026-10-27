from app.repositories import AgentRepository, ProjectRepository


async def test_project_pagination(client, admin_headers, session):
    for index in range(101):
        ProjectRepository(session).create(name=f"Project {index}")
    default_page = await client.get("/api/v1/projects", headers=admin_headers)
    full_list = await client.get("/api/v1/projects?limit=200", headers=admin_headers)
    second = await client.get("/api/v1/projects?limit=1&offset=1", headers=admin_headers)
    assert default_page.status_code == full_list.status_code == second.status_code == 200
    assert len(default_page.json()) == 50
    assert len(full_list.json()) == 101
    assert second.json() == [full_list.json()[1]]


async def test_agent_pagination(client, admin_headers, session, project):
    for index in range(3):
        AgentRepository(session).create(project_id=project.id, name=f"Agent {index}",
                                        agent_token_hash=f"hash-{index}",
                                        repository_path_hint="", git_remote="")
    all_agents = await client.get(f"/api/v1/projects/{project.id}/agents?limit=50",
                                 headers=admin_headers)
    second = await client.get(f"/api/v1/projects/{project.id}/agents?limit=1&offset=1",
                              headers=admin_headers)
    assert second.status_code == 200
    assert second.json() == [all_agents.json()[1]]
