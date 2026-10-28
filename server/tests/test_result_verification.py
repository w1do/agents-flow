import pytest

from app.schemas.git_claims import git_claims


@pytest.mark.parametrize("data,missing", [({}, True), ({"verification": None}, True),
    ({"commit_sha": "a" * 40, "verification": {"worktree_clean": True}}, False)])
async def test_result_persists_facts_and_warns_for_legacy_report(flow, data, missing):
    task = flow.task("testing", leased=True)
    fields = {"result_summary": "Done", "result_data": data, "event_id": "same-result"}
    for _ in range(2):
        assert (await flow.report(task, "result", fields)).json()["status"] == "ready"
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["result_data"] == git_claims(data)
    warnings = [e for e in card["events"] if e["event_type"] == "verification_missing"]
    assert len(warnings) == int(missing)


async def test_final_publication_updates_stored_commit_facts(flow):
    task = flow.task("merged", leased=True, result_data={"tests": ["passed"]})
    data = {"commit_sha": "b" * 40, "verification": {"head_sha": "b" * 40, "worktree_clean": True}}
    response = await flow.report(task, "publication-result", {"success": True, "message": "Committed", "payload": data})
    assert response.status_code == 200
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["result_data"] == {"tests": ["passed"]} | git_claims(data)


async def test_agent_cannot_forge_verification_warning(flow):
    task = flow.task("active", leased=True)
    response = await flow.report(task, "events", {"event_type": "verification_missing", "message": "fake"})
    assert response.status_code == 403
