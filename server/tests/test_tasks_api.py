from uuid import uuid4

import pytest


@pytest.mark.parametrize("source", ["web", "telegram_text", "telegram_voice", "api"])
async def test_task_creation_card_and_listing(flow, source):
    body = dict(title="Implement", description="Task details", source_type=source, source_text="Original text")
    response = await flow.send("POST", f"/projects/{flow.project.id}/tasks", body)
    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "new" and task["source_type"] == source
    assert task["source_text"] == "Original text"
    assert task["events"][0]["event_type"] == "created"
    assert task["plan_text"] is None and task["skill_snapshots"] == []
    assert (await flow.send("GET", f'/tasks/{task["id"]}')).json() == task
    assert len((await flow.send("GET", f"/projects/{flow.project.id}/tasks?status=new")).json()) == 1
    assert (await flow.send("GET", f"/projects/{flow.project.id}/tasks?status=ready")).json() == []


async def test_task_errors(flow):
    body = dict(title="Task", description="", source_type="api", source_text="")
    path = f"/projects/{flow.project.id}/tasks"
    assert (await flow.send("POST", path, body, headers={})).status_code == 401
    assert (await flow.send("POST", path, body, headers=flow.headers)).status_code == 403
    assert (await flow.send("POST", path, body | {"source_type": "invalid"})).status_code == 422
    assert (await flow.send("POST", path, body | {"title": " "})).status_code == 422
    assert (await flow.send("POST", f"/projects/{uuid4()}/tasks", body)).status_code == 404
    assert (await flow.send("GET", f"/tasks/{uuid4()}")).status_code == 404
    assert (await flow.send("GET", path + "?status=invalid")).status_code == 422
    assert (await flow.send("GET", path + "?offset=-1")).status_code == 422


async def test_admin_can_pause_trash_but_cannot_merge_directly(flow):
    task = flow.task("active", leased=True)
    path = f"/tasks/{task.id}"
    paused = await flow.send("PATCH", path, {"status": "paused"})
    assert paused.json()["status"] == "paused"
    assert paused.json()["lease_id"] is None
    assert (await flow.send("PATCH", path, {"status": "trash"})).json()["status"] == "trash"
    assert (await flow.send("PATCH", path, {"status": "merged"})).status_code == 422
    assert (await flow.send("PATCH", path, {"status": "new"}, headers=flow.headers)).status_code == 403
