import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core import time
from app.repositories import AgentRepository, ProjectRepository, TaskRepository
from app.services.leases import claim


async def test_claim_sets_lease_busy_and_ttl(flow, clock):
    task = flow.task()
    response = await flow.claim()
    assert response.status_code == 200
    body = response.json()
    assert body["task"]["id"] == str(task.id)
    assert body["task"]["status"] == "choosing"
    assert body["lease_id"] == body["task"]["lease_id"]
    assert time.as_utc(task.lease_expires_at) == clock[0] + timedelta(seconds=60)
    assert flow.agent.status == "busy"
    assert (await flow.claim()).status_code == 409


async def test_two_sequential_claims_give_one_task_on_sqlite(flow):
    task = flow.task()
    other, headers = flow.make_agent("Second")
    first = await flow.claim()
    second = await flow.claim(headers=headers, agent=other)
    assert first.status_code == 200 and second.status_code == 204
    assert second.content == b""
    flow.session.refresh(task)
    assert task.assigned_agent_id == flow.agent.id
    assert other.status != "busy"


async def test_claim_only_own_project_and_new_tasks(flow):
    project = ProjectRepository(flow.session).create(name="Foreign")
    foreign = flow.task(project_id=project.id)
    flow.task("backlog")
    assert (await flow.claim()).status_code == 204
    assert foreign.assigned_agent_id is None
    assert (await flow.send("POST", f"/agents/{uuid4()}/leases/claim", {}, headers=flow.headers)).status_code == 404
    assert (await flow.send("POST", f"/agents/{flow.agent.id}/leases/claim", {}, headers={})).status_code == 401
    assert (await flow.claim(headers=flow.admin)).status_code == 403


async def test_heartbeat_extends_and_idle_updates_online(flow, clock):
    idle = await flow.send("POST", f"/agents/{flow.agent.id}/heartbeat", {"task_id": None, "lease_id": None}, headers=flow.headers)
    assert idle.json() == {"status": "online", "lease_expires_at": None}
    task = flow.task()
    await flow.claim()
    clock[0] += timedelta(seconds=20)
    body = dict(task_id=str(task.id), lease_id=str(task.lease_id))
    response = await flow.send("POST", f"/agents/{flow.agent.id}/heartbeat", body, headers=flow.headers)
    assert response.status_code == 200
    assert time.as_utc(task.lease_expires_at) == clock[0] + timedelta(seconds=60)
    assert time.as_utc(flow.agent.last_heartbeat_at) == clock[0]
    assert flow.agent.status == "busy"
    invalid = body | {"lease_id": str(uuid4())}
    assert (await flow.send("POST", f"/agents/{flow.agent.id}/heartbeat", invalid, headers=flow.headers)).status_code == 409
    assert (await flow.send("POST", f"/agents/{flow.agent.id}/heartbeat", body | {"lease_id": None}, headers=flow.headers)).status_code == 422


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"),
                    reason="Параллельные FOR UPDATE SKIP LOCKED проверяются при PostgreSQL TEST_DATABASE_URL; SQLite проверяется последовательно")
async def test_two_parallel_claims_postgresql(flow, engine):
    task = flow.task()
    other, _ = flow.make_agent("Parallel")
    barrier = Barrier(2)

    def run(agent_id):
        with Session(engine) as session:
            agent = AgentRepository(session).get(agent_id)
            barrier.wait(timeout=10)
            response = claim(session, agent)
            session.commit()
            return response.task.id if response else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [flow.agent.id, other.id]))
    assert results.count(task.id) == 1 and results.count(None) == 1
