from datetime import timedelta
from uuid import uuid4

import pytest

from app.repositories import ProjectRepository
from mcp_helpers import CALLS


@pytest.mark.parametrize("method", ["POST", "GET", "DELETE"])
@pytest.mark.parametrize("credential", ["missing", "invalid", "admin", "basic"])
async def test_transport_requires_agent_token_before_protocol(flow, method, credential):
    headers = {"Accept": "application/json, text/event-stream"}
    if credential == "invalid":
        headers["Authorization"] = "Bearer invalid-agent-token"
    elif credential == "admin":
        headers |= flow.admin
    elif credential == "basic":
        headers["Authorization"] = flow.headers["Authorization"].replace("Bearer", "Basic")
    response = await flow.client.request(method, "/mcp", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"error": {"code": 401, "message": "Unauthorized"}}


@pytest.mark.parametrize("name,status,fields", CALLS)
async def test_every_tool_rejects_foreign_task_and_invalid_lease(flow, mcp, mcp_factory, name, status, fields):
    task = flow.task(status, leased=True)
    other, headers = flow.make_agent("Other")
    async with mcp_factory(headers) as colleague:
        result = await colleague.call(name, task, fields)
    assert result["error"]["code"] == 409
    result = await mcp.call(name, task, fields | {"lease_id": str(uuid4())})
    assert result["error"]["code"] == 409
    project = ProjectRepository(flow.session).create(name="Foreign")
    foreign = flow.task(status, leased=True, project_id=project.id)
    assert (await mcp.call(name, foreign, fields))["error"]["code"] == 404
    assert (await mcp.call(name, task, fields | {"task_id": str(uuid4())}))["error"]["code"] == 404
    flow.session.refresh(task)
    assert task.status == status
    assert task.checkpoint is None


@pytest.mark.parametrize("name,status,fields", CALLS)
async def test_every_tool_requires_event_id_and_current_lease(flow, mcp, clock, name, status, fields):
    task = flow.task(status, leased=True)
    for field in ("event_id", "lease_id"):
        arguments = dict(task_id=str(task.id), lease_id=str(task.lease_id), event_id="event") | fields
        del arguments[field]
        result = await mcp.raw(name, arguments)
        assert result.is_error and result.structured_content["error"]["code"] == 422
    clock[0] += timedelta(seconds=61)
    assert (await mcp.call(name, task, fields))["error"]["code"] == 409
    flow.session.refresh(task)
    assert task.lease_id is None
    assert task.status == ("merged" if status == "merged" else "stalled")


async def test_rest_and_health_remain_available(flow):
    assert (await flow.client.get("/healthz")).status_code == 200
    task = flow.task("active", leased=True)
    assert (await flow.state(task)).status_code == 200


async def test_token_is_rechecked_after_client_connects(flow, mcp):
    from app.services.agent_auth import generate_agent_token

    flow.agent.agent_token_hash = generate_agent_token()[1]
    flow.session.commit()
    response = await flow.client.post("/mcp", headers=flow.headers)
    assert response.status_code == 401


async def test_authentication_backend_error_is_compact(flow, monkeypatch):
    from app.mcp import transport

    secret = flow.headers["Authorization"].split()[1]

    def fail(_token):
        raise RuntimeError("/internal/path " + secret)

    monkeypatch.setattr(transport, "agent_identity", fail)
    response = await flow.client.post("/mcp", headers=flow.headers)
    assert response.status_code == 500
    assert response.json() == {"error": {"code": 500, "message": "Internal error"}}
