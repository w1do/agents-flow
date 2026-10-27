from datetime import timedelta

import pytest

from app.core import time
from app.services.lease_expiry import expire_due


async def test_expiry_preserves_checkpoint_history_and_admin_restart(flow, clock):
    task = flow.task("planning", leased=True, checkpoint={"step": 3}, result_summary="Partial")
    progress = await flow.report(task, "events", {"event_type": "progress", "message": "Work"})
    assert progress.status_code == 200
    old_lease = task.lease_id
    clock[0] += timedelta(seconds=60)
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["status"] == "stalled" and flow.agent.status == "offline"
    assert card["checkpoint"] == {"step": 3} and card["result_summary"] == "Partial"
    assert [e["event_type"] for e in card["events"]] == ["progress", "lease_expired"]
    assert (await flow.report(task, "plan", {"plan_text": "Late", "lease_id": str(old_lease)})).status_code == 409
    assert (await flow.send("PATCH", f"/tasks/{task.id}", {"status": "new"}, headers=flow.headers)).status_code == 403
    restarted = await flow.send("PATCH", f"/tasks/{task.id}", {"status": "new"})
    assert restarted.status_code == 200 and restarted.json()["lease_id"] is None
    claimed = await flow.claim()
    assert claimed.json()["task"]["checkpoint"] == {"step": 3}
    assert task.lease_id != old_lease
    assert (await flow.state(task)).json()["checkpoint"] == {"step": 3}


@pytest.mark.parametrize("endpoint,fields", [
    ("plan", {"plan_text": "Late"}), ("events", {"event_type": "progress", "message": "Late"}),
    ("result", {"result_summary": "Late", "result_data": {}}),
    ("publication-result", {"success": True, "message": "Late"}), ("fail", {"message": "Late"}),
])
async def test_all_reports_reject_expired_lease(flow, clock, endpoint, fields):
    task = flow.task("planning", leased=True)
    clock[0] += timedelta(seconds=61)
    assert (await flow.report(task, endpoint, fields)).status_code == 409
    flow.session.refresh(task)
    assert task.status == "stalled"
    assert flow.agent.status == "offline"


async def test_expired_heartbeat_and_state_rejected(flow, clock):
    task = flow.task("active", leased=True)
    lease_id = task.lease_id
    clock[0] += timedelta(seconds=61)
    body = dict(task_id=str(task.id), lease_id=str(task.lease_id))
    assert (await flow.send("POST", f"/agents/{flow.agent.id}/heartbeat", body, headers=flow.headers)).status_code == 409
    state = await flow.send("GET", f"/tasks/{task.id}/execution-state?lease_id={lease_id}",
                            headers=flow.headers)
    assert state.status_code == 409
    idle = await flow.send("POST", f"/agents/{flow.agent.id}/heartbeat", {"task_id": None, "lease_id": None}, headers=flow.headers)
    assert idle.json()["status"] == "online"
    assert task.status == "stalled"


async def test_expiry_worker_operation_is_repeatable(flow, clock):
    task = flow.task("active", leased=True)
    clock[0] += timedelta(seconds=61)
    expire_due(flow.session)
    expire_due(flow.session)
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert len(card["events"]) == 1
    assert card["events"][0]["event_type"] == "lease_expired"
