from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import IdempotencyKey, Task


async def test_task_rest_idempotency_conflict_new_key_and_required_header(flow):
    body = dict(title="Task", description="", source_type="api", source_text="Original")
    path = f"/projects/{flow.project.id}/tasks"
    key = str(uuid4())
    first = await flow.send("POST", path, body, key=key)
    repeated = await flow.send("POST", path, body, key=key)
    assert first.status_code == repeated.status_code == 201
    assert first.content == repeated.content
    changed = await flow.send("POST", path, body | {"title": "Changed"}, key=key)
    assert changed.status_code == 409
    another = await flow.send("POST", path, body)
    assert another.json()["id"] != first.json()["id"]
    assert flow.session.scalar(select(func.count()).select_from(Task)) == 2
    assert flow.session.scalar(select(func.count()).select_from(IdempotencyKey)) == 2
    assert (await flow.client.post("/api/v1" + path, json=body, headers=flow.admin)).status_code == 422


async def test_claim_replays_success_and_empty_response(flow):
    task = flow.task()
    key = str(uuid4())
    first = await flow.claim(key=key)
    repeated = await flow.claim(key=key)
    assert first.content == repeated.content and repeated.status_code == 200
    assert (await flow.claim()).status_code == 409
    other, headers = flow.make_agent("Other")
    empty_key = str(uuid4())
    assert (await flow.claim(agent=other, headers=headers, key=empty_key)).status_code == 204
    flow.task()
    repeated = await flow.claim(agent=other, headers=headers, key=empty_key)
    assert repeated.status_code == 204 and repeated.content == b""
    assert (await flow.claim(agent=other, headers=headers)).status_code == 200


@pytest.mark.parametrize("kind,status,fields", [
    ("plan", "planning", {"plan_text": "Plan"}),
    ("events", "active", {"event_type": "progress", "message": "Step"}),
    ("result", "testing", {"result_summary": "Done", "result_data": {}}),
    ("publication-result", "merged", {"success": True, "message": "Done"}),
    ("fail", "active", {"message": "Error"}),
])
async def test_event_id_deduplicates_all_reports(flow, kind, status, fields):
    task = flow.task(status, leased=True)
    first = await flow.report(task, kind, fields, event_id="event-1")
    repeated = await flow.report(task, kind, fields, event_id="event-1")
    assert first.status_code == repeated.status_code == 200
    assert first.json() == repeated.json()
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    reports = [event for event in card["events"] if event["event_id"] == "event-1"]
    assert len(reports) == 1
    assert [event["event_type"] for event in card["events"]] == (
        ["verification_missing", "result"] if kind == "result" else [kind if kind != "events" else "progress"])


async def test_decision_replay_does_not_increment_twice_and_scope_is_per_endpoint(flow):
    task = flow.task("backlog", leased=True)
    key = str(uuid4())
    path = f"/tasks/{task.id}/plan/decision"
    body = {"decision": "rejected", "feedback": "Tests"}
    first = await flow.send("POST", path, body, key=key)
    repeated = await flow.send("POST", path, body, key=key)
    assert first.content == repeated.content and repeated.json()["plan_revision"] == 1
    await flow.report(task, "plan", {"plan_text": "New plan"}, key=key)
    assert task.status == "backlog"
    assert (await flow.send("POST", path, body | {"feedback": "Other"}, key=key)).status_code == 409


async def test_failed_operation_rolls_back_key_and_body_changes(flow):
    task = flow.task("choosing", leased=True)
    key = str(uuid4())
    fields = {"plan_text": "Plan"}
    assert (await flow.report(task, "plan", fields, key=key)).status_code == 409
    assert flow.session.scalar(select(func.count()).select_from(IdempotencyKey)) == 0
    await flow.report(task, "events", {"event_type": "planning", "message": "Start"})
    assert (await flow.report(task, "plan", fields, key=key)).status_code == 200
