from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.repositories import AgentSkillRepository
from mcp_helpers import CALLS


async def test_sdk_lists_exact_contract_and_required_arguments(mcp):
    tools = (await mcp.sdk.list_tools()).tools
    assert {tool.name for tool in tools} == {row[0] for row in CALLS}
    assert len(tools) == 11
    for tool in tools:
        assert {"event_id", "lease_id"} <= set(tool.input_schema["required"])
        assert tool.input_schema["additionalProperties"] is False


async def test_full_mcp_execution_visible_through_rest(flow, mcp, clock):
    task = flow.task()
    await flow.claim()
    assert (await mcp.call("agent_report_progress", task, {
        "event_type": "planning", "message": "Planning",
    }))["status"] == "planning"
    assert (await mcp.call("agent_report_plan", task, {"plan_text": "Implement"}))["status"] == "backlog"
    state = await mcp.call("agent_get_plan_decision", task)
    assert state["plan_decision"] == "pending"
    await flow.send("POST", f"/tasks/{task.id}/plan/decision", {"decision": "approved"})
    assert (await mcp.call("agent_get_plan_decision", task))["plan_decision"] == "approved"
    clock[0] += timedelta(seconds=20)
    heartbeat = await mcp.call("agent_heartbeat", task)
    assert heartbeat["status"] == "busy"
    assert datetime.fromisoformat(heartbeat["lease_expires_at"]) == clock[0] + timedelta(seconds=60)
    await mcp.call("agent_save_checkpoint", task, {"checkpoint": {"step": "tests"}})
    await mcp.call("agent_report_progress", task, {"event_type": "testing", "message": "Testing"})
    await mcp.call("agent_report_test_result", task, {"message": "Passed", "payload": {"passed": 5}})
    result = await mcp.call("agent_report_result", task, {"result_summary": "Done", "result_data": {"tests": "passed"}})
    assert result["status"] == "ready"
    assert (await mcp.call("agent_get_result_decision", task))["publication_requested"] is False
    denied = await mcp.call("agent_report_publication_result", task, {"success": True, "message": "Too early"})
    assert denied["error"]["code"] == 409
    await flow.send("POST", f"/tasks/{task.id}/result/decision", {"decision": "publish"})
    assert (await mcp.call("agent_get_result_decision", task))["publication_requested"] is True
    published = await mcp.call("agent_report_publication_result", task, {"success": False, "message": "Failed push"})
    assert published["status"] == "merged"
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["checkpoint"] == {"step": "tests"} and card["completed_at"]
    assert card["result_data"] == {"tests": "passed"}
    assert next(e for e in card["events"] if e["event_type"] == "test_result")["payload"]["payload"] == {"passed": 5}
    flow.session.refresh(flow.agent)
    assert flow.agent.status == "online"
    assert (await mcp.call("agent_get_result_decision", task))["publication_requested"] is False


async def test_assigned_task_returns_lease_checkpoint_decisions_and_frozen_skills(flow, mcp):
    skill = flow.skill()
    AgentSkillRepository(flow.session).create(agent_id=flow.agent.id, skill_id=skill.id)
    flow.session.commit()
    task = flow.task()
    claimed = (await flow.claim()).json()
    await flow.send("PATCH", f"/skills/{skill.id}", {"content": "Updated skill"})
    await mcp.call("agent_save_checkpoint", task, {"checkpoint": {"step": 2}})
    result = await mcp.raw("agent_get_assigned_task", {"lease_id": claimed["lease_id"], "event_id": "read-task"})
    card = result.structured_content["task"]
    assert card["id"] == str(task.id) and card["lease_id"] == claimed["lease_id"]
    assert card["skill_snapshots"] == claimed["task"]["skill_snapshots"]
    assert result.structured_content["execution_state"]["checkpoint"] == {"step": 2}


@pytest.mark.parametrize("name,status,fields", [row for row in CALLS if row[0].startswith("agent_report_") or row[0] == "agent_save_checkpoint"])
async def test_report_retries_are_idempotent_and_each_call_is_audited(flow, mcp, name, status, fields):
    task = flow.task(status, leased=True)
    event_id = str(uuid4())
    first = await mcp.call(name, task, fields, event_id=event_id)
    assert "error" not in first
    assert await mcp.call(name, task, fields, event_id=event_id) == first
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert sum(e["event_id"] == event_id for e in card["events"]) == 1
    assert sum(e["event_type"] == "mcp_" + name.removeprefix("agent_") for e in card["events"]) == 2


async def test_mcp_and_rest_share_event_id_deduplication(flow, mcp):
    task = flow.task("active", leased=True)
    fields = {"event_type": "progress", "message": "Once"}
    event_id = str(uuid4())
    await flow.report(task, "events", fields, event_id=event_id)
    await mcp.call("agent_report_progress", task, fields, event_id=event_id)
    await flow.report(task, "events", fields, event_id=event_id)
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert sum(e["event_id"] == event_id for e in card["events"]) == 1


async def test_failure_uses_same_rest_state_and_preserves_checkpoint(flow, mcp):
    task = flow.task("active", leased=True, checkpoint={"step": 1}, result_summary="Partial")
    result = await mcp.call("agent_report_failure", task, {"message": "Build failed"})
    assert result["status"] == "error"
    flow.session.refresh(task)
    flow.session.refresh(flow.agent)
    assert task.checkpoint == {"step": 1} and task.result_summary == "Partial"
    assert flow.agent.status == "online"


@pytest.mark.parametrize("mode", ["auto", "2026-07-28"])
async def test_modern_sdk_uses_same_http_endpoint(flow, mcp_factory, mode):
    task = flow.task("active", leased=True)
    async with mcp_factory(mode=mode) as client:
        assert len((await client.sdk.list_tools()).tools) == 11
        assert (await client.call("agent_heartbeat", task))["status"] == "busy"


@pytest.mark.parametrize("name,status,fields", CALLS)
async def test_each_tool_matches_rest_state(flow, mcp, clock, name, status, fields):
    first, second = [flow.task(status, leased=True) for _ in range(2)]
    result = await mcp.call(name, first, fields)
    assert "error" not in result
    paths = {"agent_report_plan": "plan", "agent_report_progress": "events",
             "agent_report_result": "result", "agent_report_failure": "fail",
             "agent_report_publication_result": "publication-result"}
    if name in paths:
        response = await flow.report(second, paths[name], fields)
    elif name == "agent_save_checkpoint":
        response = await flow.report(second, "events", fields | {
            "event_type": "checkpoint", "message": "Checkpoint saved"})
    elif name == "agent_report_test_result":
        response = await flow.report(second, "events", fields | {"event_type": "test_result"})
    elif name == "agent_heartbeat":
        response = await flow.send("POST", f"/agents/{flow.agent.id}/heartbeat", {
            "task_id": str(second.id), "lease_id": str(second.lease_id)}, headers=flow.headers)
    else:
        response = await flow.state(second)
        state = result["execution_state"] if name == "agent_get_assigned_task" else result
        assert {k: v for k, v in state.items() if k not in {"task_id", "lease_id"}} == {
            k: v for k, v in response.json().items() if k not in {"task_id", "lease_id"}}
    assert response.status_code == 200
    cards = [(await flow.send("GET", f"/tasks/{task.id}")).json() for task in (first, second)]
    keys = {"status", "plan_text", "plan_decision", "checkpoint", "result_summary",
            "result_data", "completed_at", "lease_expires_at"}
    assert {key: cards[0][key] for key in keys} == {key: cards[1][key] for key in keys}
