import pytest


async def test_plan_rejected_increments_revision_and_approved_starts_work(flow):
    task = flow.task("backlog", leased=True, plan_text="Initial")
    path = f"/tasks/{task.id}/plan/decision"
    response = await flow.send("POST", path, {"decision": "rejected", "feedback": "Add tests"})
    assert response.json()["status"] == "planning"
    assert response.json()["plan_revision"] == 1 and response.json()["plan_feedback"] == "Add tests"
    assert (await flow.state(task)).json()["plan_feedback"] == "Add tests"
    await flow.report(task, "plan", {"plan_text": "With tests"})
    approved = await flow.send("POST", path, {"decision": "approved"})
    assert approved.json()["status"] == "active"
    assert approved.json()["plan_decision"] == "approved"
    assert approved.json()["plan_revision"] == 1
    assert (await flow.send("POST", path, {"decision": "approved"})).status_code == 409


@pytest.mark.parametrize("decision,target,feedback", [("publish", "merged", None),
                                                       ("keep_ready", "ready", None),
                                                       ("rework", "active", "Fix tests")])
async def test_result_decisions_and_execution_state(flow, decision, target, feedback):
    task = flow.task("ready", leased=True)
    body = dict(decision=decision, feedback=feedback)
    response = await flow.send("POST", f"/tasks/{task.id}/result/decision", body)
    assert response.status_code == 200 and response.json()["status"] == target
    state = (await flow.state(task)).json()
    assert state["result_feedback"] == feedback
    assert state["publication_requested"] == (decision == "publish")


@pytest.mark.parametrize("kind,status,decision", [("plan", "backlog", "approved"), ("result", "ready", "publish")])
async def test_agent_cannot_make_decisions(flow, kind, status, decision):
    task = flow.task(status, leased=True)
    response = await flow.send("POST", f"/tasks/{task.id}/{kind}/decision", {"decision": decision}, headers=flow.headers)
    assert response.status_code == 403
    assert task.status == status


@pytest.mark.parametrize("kind,decision", [("plan", "rejected"), ("result", "rework")])
async def test_feedback_required(flow, kind, decision):
    task = flow.task("backlog" if kind == "plan" else "ready")
    path = f"/tasks/{task.id}/{kind}/decision"
    for feedback in (None, "", "   "):
        assert (await flow.send("POST", path, dict(decision=decision, feedback=feedback))).status_code == 422


async def test_trash_plan_and_invalid_decisions(flow):
    task = flow.task("backlog", leased=True)
    response = await flow.send("POST", f"/tasks/{task.id}/plan/decision", {"decision": "trash"})
    assert response.json()["status"] == "trash" and response.json()["lease_id"] is None
    assert (await flow.send("POST", f"/tasks/{task.id}/plan/decision", {"decision": "publish"})).status_code == 422
    assert (await flow.send("POST", f"/tasks/{task.id}/result/decision", {"decision": "publish"})).status_code == 409
