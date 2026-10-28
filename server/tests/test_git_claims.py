"""Agent Git assertions remain bounded, untrusted claims at the HTTP boundary."""
import pytest


@pytest.mark.parametrize("kind", ["result", "publication-result"])
async def test_git_facts_are_claims_with_unknown_fields_dropped(flow, kind):
    task = flow.task("testing" if kind == "result" else "merged", leased=True)
    sha = "a" * 40
    facts = {"commit_sha": sha, "verification": {"head_sha": sha, "worktree_clean": True,
             "commits": [{"sha": sha, "subject": "fixture", "unknown": "drop"}], "unknown": "drop"}}
    fields = {"result_summary": "Done", "result_data": facts} if kind == "result" else {
        "success": True, "message": "Done", "payload": facts}
    assert (await flow.report(task, kind, fields)).status_code == 200
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    stored = card["result_data"]
    assert stored["commit_sha"] == sha
    assert "verification" not in stored
    assert stored["claims"] == {"source": "agent_reported", "head_sha": sha, "worktree_clean": True,
                                 "commits": [{"sha": sha, "subject": "fixture"}]}
    assert card["status"] == ("ready" if kind == "result" else "merged")


@pytest.mark.parametrize("kind", ["result", "publication-result"])
@pytest.mark.parametrize("data", [
    {"commit_sha": "invalid"}, {"verification": {"head_sha": "bad"}},
    *[{"verification": {"diff_name_only": [path]}} for path in
      ["../a", "/tmp/a", ".env.local", "src/.secrets/a", "C:\\tmp\\a"]],
    {"verification": {"commits": [{"sha": "b" * 40, "subject": "x"}] * 101}},
])
async def test_invalid_git_claims_rejected(flow, data, kind):
    task = flow.task("testing" if kind == "result" else "merged", leased=True)
    fields = {"result_summary": "Done", "result_data": data} if kind == "result" else {
        "success": True, "message": "Done", "payload": data}
    response = await flow.report(task, kind, fields)
    assert response.status_code == 422


async def test_commit_saved_without_verification(flow):
    task = flow.task("merged", leased=True, result_data={"tests": ["passed"]})
    sha = "b" * 40
    response = await flow.report(task, "publication-result", {
        "success": True, "message": "Done", "payload": {"commit_sha": sha}})
    assert response.status_code == 200
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["result_data"] == {"tests": ["passed"], "commit_sha": sha}


async def test_direct_claims_cannot_claim_server_provenance(flow):
    task = flow.task("testing", leased=True)
    fields = {"result_summary": "Done", "result_data": {"claims": {
        "source": "server_verified", "head_sha": "c" * 40, "accepted": True}}}
    assert (await flow.report(task, "result", fields)).status_code == 200
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["result_data"] == {"claims": {"source": "agent_reported", "head_sha": "c" * 40}}
    event = next(event for event in card["events"] if event["event_type"] == "result")
    assert event["payload"]["result_data"] == card["result_data"]
    assert card["status"] == "ready"
