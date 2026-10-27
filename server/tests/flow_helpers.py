from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core import time
from app.repositories import AgentRepository, SkillCategoryRepository, SkillRepository, TaskRepository
from app.services.agent_auth import generate_agent_token
from app.services.skill_content import content_values


class Flow:
    def __init__(self, client, session, project, admin):
        self.client, self.session, self.project, self.admin = client, session, project, admin
        self.agent, self.headers = self.make_agent("Worker")

    def make_agent(self, name, project_id=None):
        token, token_hash = generate_agent_token()
        agent = AgentRepository(self.session).create(
            project_id=project_id or self.project.id, name=name, agent_token_hash=token_hash,
            repository_path_hint="", git_remote="",
        )
        self.session.commit()
        return agent, {"Authorization": f"Bearer {token}"}

    def task(self, status="new", leased=False, **values):
        fields = dict(project_id=self.project.id, title="Build", description="Feature",
                      source_type="api", source_text="Request", status=status)
        if leased:
            fields.update(assigned_agent_id=self.agent.id, lease_id=uuid4(),
                          lease_expires_at=time.now() + timedelta(seconds=60))
        task = TaskRepository(self.session).create(**(fields | values))
        self.session.commit()
        return task

    def skill(self, name="Проверки", category="Разработка", **values):
        category = SkillCategoryRepository(self.session).create(name=category, description="")
        skill = SkillRepository(self.session).create(
            category_id=category.id, name=name, description="", **(content_values("Run tests") | values),
        )
        self.session.commit()
        return skill

    async def send(self, method, path, body=None, *, headers=None, key=None):
        authorization = self.admin if headers is None else headers
        return await self.client.request(method, "/api/v1" + path, json=body,
                                         headers=authorization | {"Idempotency-Key": key or str(uuid4())})

    async def claim(self, *, headers=None, agent=None, key=None):
        return await self.send("POST", f"/agents/{(agent or self.agent).id}/leases/claim", {},
                               headers=headers or self.headers, key=key)

    async def report(self, task, kind, fields=None, *, headers=None, event_id=None, key=None):
        body = dict(lease_id=str(task.lease_id), event_id=event_id or str(uuid4()))
        return await self.send("POST", f"/tasks/{task.id}/{kind}", body | (fields or {}),
                               headers=headers or self.headers, key=key)

    async def state(self, task, **kwargs):
        return await self.send("GET", f"/tasks/{task.id}/execution-state?lease_id={task.lease_id}",
                               headers=self.headers, **kwargs)


@pytest.fixture
async def flow(client, session, project, admin_headers):
    return Flow(client, session, project, admin_headers)


@pytest.fixture
def clock(monkeypatch):
    values = [datetime(2026, 10, 27, tzinfo=timezone.utc)]
    monkeypatch.setattr(time, "now", lambda: values[0])
    return values
