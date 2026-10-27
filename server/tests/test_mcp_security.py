import json

import pytest


@pytest.mark.parametrize("name", [
    "agent_approve_plan", "agent_accept_result", "agent_plan_decision", "agent_result_decision",
    "agent_confirm_plan", "agent_confirm_result", "agent_sync_skills",
])
@pytest.mark.parametrize("status", ["backlog", "ready"])
async def test_unexposed_tools_cannot_approve_or_change_state(flow, mcp, name, status):
    task = flow.task(status, leased=True, plan_text="Plan", plan_decision="pending")
    assert name not in {tool.name for tool in (await mcp.sdk.list_tools()).tools}
    result = await mcp.call(name, task, {"decision": "approved"})
    assert result["error"]["code"] == 404
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["status"] == status and card["plan_decision"] == "pending"
    assert not any(e["event_type"] in {"plan_decision", "result_decision"} for e in card["events"])


@pytest.mark.parametrize("status", ["backlog", "ready"])
async def test_agent_cannot_set_merged(flow, mcp, status):
    task = flow.task(status, leased=True)
    fields = {"event_type": "progress", "message": "Merge", "payload": {"status": "merged"}}
    mcp_result = await mcp.call("agent_report_progress", task, fields)
    rest_result = await flow.report(task, "events", fields)
    assert mcp_result["error"]["code"] == rest_result.status_code
    assert rest_result.status_code in {403, 409}
    flow.session.refresh(task)
    assert task.status == status


async def test_checkpoint_audit_is_compact_and_payload_is_sanitized(flow, mcp, caplog):
    task = flow.task("active", leased=True)
    token = flow.headers["Authorization"].split()[1]
    secret = "ghp_" + "x" * 36
    payload = {"step": "A long private implementation checkpoint", "credential": token, "nested": [secret]}
    result = await mcp.call("agent_save_checkpoint", task, {"checkpoint": payload})
    assert "error" not in result
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    audit = next(e for e in card["events"] if e["event_type"] == "mcp_save_checkpoint")
    assert audit["payload"] == {"code": 200}
    assert audit["agent_id"] == str(flow.agent.id)
    assert payload["step"] not in json.dumps(audit)
    assert card["checkpoint"]["credential"] == "[REDACTED]"
    assert token not in json.dumps(card) + caplog.text
    assert secret not in json.dumps(card) + caplog.text


@pytest.mark.parametrize("invalid", ["checkpoint", "event_id", "lease_id", "extra", "event_type"])
async def test_validation_errors_never_echo_input_or_tracebacks(flow, mcp, caplog, invalid):
    task = flow.task("active", leased=True)
    secret = flow.headers["Authorization"].split()[1]
    arguments = dict(task_id=str(task.id), lease_id=str(task.lease_id), event_id="safe", checkpoint={"step": 1})
    if invalid == "extra":
        arguments[secret] = "PRIVATE SKILL CONTENT"
    else:
        arguments[invalid] = secret
    result = await mcp.raw("agent_save_checkpoint", arguments)
    assert result.is_error
    assert result.structured_content == {"error": {"code": 422, "message": "Invalid arguments"}}
    output = result.model_dump_json() + caplog.text
    assert not any(text in output for text in [secret, "PRIVATE SKILL CONTENT", "Traceback", "/home/dev/", "ValidationError"])
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["checkpoint"] is None
    assert card["events"][-1]["payload"] == {"code": 422}


@pytest.mark.parametrize("event_type", ["plan_decision", "result_decision", "merged", "lease_expired", "mcp_save_checkpoint"])
async def test_reserved_events_cannot_spoof_decisions(flow, mcp, event_type):
    task = flow.task("backlog", leased=True)
    result = await mcp.call("agent_report_progress", task, {"event_type": event_type, "message": "Approve"})
    assert result["error"]["code"] == 403
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["status"] == "backlog" and card["plan_decision"] == "pending"
    assert not any(e["event_type"] == event_type for e in card["events"])
    rest = await flow.report(task, "events", {"event_type": event_type, "message": "Fake"})
    assert rest.status_code == 403


async def test_malformed_http_envelope_does_not_echo_credentials(flow):
    secret = flow.headers["Authorization"].split()[1]
    response = await flow.client.post("/mcp", headers=flow.headers | {
        "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25",
    }, json={"jsonrpc": "wrong", "id": 1, "method": "tools/call", "params": {"name": secret}})
    assert response.status_code == 400
    assert secret not in response.text and "ValidationError" not in response.text


async def test_json_rpc_errors_at_http_200_do_not_echo_arguments(flow):
    secret = flow.headers["Authorization"].split()[1]
    response = await flow.client.post("/mcp", headers=flow.headers | {
        "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25",
    }, json={"jsonrpc": "2.0", "id": 1, "method": secret, "params": {"token": secret}})
    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0" and body["id"] == 1 and "error" in body
    assert secret not in response.text


@pytest.mark.parametrize("name,fields", [
    ("agent_report_test_result", {"message": "Passed", "payload": {"status": "testing"}}),
    ("agent_save_checkpoint", {"checkpoint": {"step": 1}, "payload": {"status": "testing"}}),
])
async def test_checkpoint_and_test_result_do_not_change_task_status(flow, mcp, name, fields):
    task = flow.task("active", leased=True)
    result = await mcp.call(name, task, fields)
    assert result["status"] == "active"
    flow.session.refresh(task)
    assert task.status == "active"


async def test_internal_failure_rolls_back_and_returns_no_details(flow, mcp, monkeypatch, caplog):
    from app.services import mcp_tools
    from app.services.leases import agent_task

    task = flow.task("active", leased=True)
    secret = flow.headers["Authorization"].split()[1]

    def fail(session, agent, _name, body):
        owned = agent_task(session, body.task_id, agent, body.lease_id)
        owned.checkpoint = {"bad": True}
        session.flush()
        raise RuntimeError("/internal/path " + secret)

    monkeypatch.setattr(mcp_tools, "execute", fail)
    result = await mcp.call("agent_save_checkpoint", task, {"checkpoint": {"step": 1}})
    assert result == {"error": {"code": 500, "message": "Internal error"}}
    flow.session.refresh(task)
    assert task.checkpoint is None
    assert secret not in json.dumps(result) + caplog.text
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["events"][-1]["event_type"] == "mcp_save_checkpoint"
    assert card["events"][-1]["payload"] == {"code": 500}
