from uuid import uuid4

import pytest

from app.repositories import ProjectRepository

REPORTS = [
    ("plan", {"plan_text": "Plan"}), ("events", {"event_type": "progress", "message": "Step"}),
    ("result", {"result_summary": "Done", "result_data": {"files": ["main.py"], "tests": "passed"}}),
    ("publication-result", {"success": True, "message": "Pushed"}), ("fail", {"message": "Failure"}),
]


async def test_full_execution_flow_and_events(flow):
    task = flow.task()
    assert (await flow.claim()).status_code == 200
    assert (await flow.report(task, "events", {"event_type": "planning", "message": "Planning"})).json()["status"] == "planning"
    assert (await flow.report(task, "plan", {"plan_text": "Implement feature"})).json()["status"] == "backlog"
    decision = await flow.send("POST", f"/tasks/{task.id}/plan/decision", {"decision": "approved"})
    assert decision.json()["status"] == "active"
    progress = dict(event_type="testing", message="Tests", checkpoint={"step": "tests"}, payload={"passed": 5})
    assert (await flow.report(task, "events", progress)).json()["status"] == "testing"
    result = await flow.report(task, "result", {"result_summary": "Implemented", "result_data": {"files": ["main.py"], "tests": "passed"}})
    assert result.json()["status"] == "ready"
    assert (await flow.state(task)).json()["publication_requested"] is False
    assert (await flow.report(task, "publication-result", {"success": True, "message": "Too early"})).status_code == 409
    await flow.send("POST", f"/tasks/{task.id}/result/decision", {"decision": "publish"})
    assert (await flow.state(task)).json()["publication_requested"] is True
    published = await flow.report(task, "publication-result", {"success": False, "message": "Push failed"})
    assert published.json()["status"] == "merged"
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["result_data"]["files"] == ["main.py"]
    assert card["checkpoint"] == {"step": "tests"}
    assert card["completed_at"] is not None
    assert card["events"][-1]["payload"]["success"] is False
    assert (await flow.state(task)).json()["publication_requested"] is False
    assert flow.agent.status == "online"
    flow.task()
    assert (await flow.claim()).status_code == 200


@pytest.mark.parametrize("kind,fields", REPORTS)
async def test_reports_reject_foreign_or_wrong_lease(flow, kind, fields):
    task = flow.task("planning", leased=True)
    other, headers = flow.make_agent("Other")
    assert (await flow.report(task, kind, fields, headers=headers)).status_code == 409
    assert (await flow.report(task, kind, fields | {"lease_id": str(uuid4())})).status_code == 409
    assert (await flow.report(task, kind, fields, headers=flow.admin)).status_code == 403
    assert (await flow.report(task, kind, fields | {"event_id": ""})).status_code == 422
    project = ProjectRepository(flow.session).create(name="Foreign")
    foreign = flow.task("planning", leased=True, project_id=project.id)
    assert (await flow.report(foreign, kind, fields)).status_code == 404
    assert (await flow.send("POST", f"/tasks/{uuid4()}/{kind}", dict(lease_id=str(uuid4()), event_id="missing") | fields, headers=flow.headers)).status_code == 404


async def test_fail_preserves_prior_events_checkpoint_and_result(flow):
    task = flow.task("active", leased=True, result_summary="Partial")
    await flow.report(task, "events", dict(event_type="progress", message="Step one", checkpoint={"step": 1}))
    before = (await flow.send("GET", f"/tasks/{task.id}")).json()["events"]
    assert (await flow.report(task, "fail", {"message": "Build failed"})).json()["status"] == "error"
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["events"][:-1] == before
    assert card["events"][-1]["event_type"] == "fail"
    assert card["checkpoint"] == {"step": 1} and card["result_summary"] == "Partial"
    assert flow.agent.status == "online"


async def test_invalid_status_and_attempt_to_self_approve(flow):
    task = flow.task("backlog", leased=True)
    invalid = await flow.report(task, "events", dict(event_type="status", message="Skip", payload={"status": "merged"}))
    assert invalid.status_code == 409 and task.status == "backlog"
    invalid = await flow.report(task, "events", dict(event_type="testing", message="Skip"))
    assert invalid.status_code == 409
    assert (await flow.report(task, "plan", {"plan_text": "Wrong status"})).status_code == 409
    assert (await flow.report(task, "result", {"result_summary": "Skip", "result_data": {}})).status_code == 409
