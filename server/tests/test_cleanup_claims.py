"""Cleanup warnings survive both reporting APIs without gaining authority."""
import pytest


@pytest.mark.parametrize("kind", ["result", "publication-result"])
@pytest.mark.parametrize("container", ["claims", "verification"])
@pytest.mark.parametrize("value", [True, False, None])
async def test_cleanup_flag_is_saved_as_agent_claim(flow, kind, container, value):
    task = flow.task("testing" if kind == "result" else "merged", leased=True)
    sha = "a" * 40
    data = {"commit_sha": sha, container: {"source": "server_verified", "head_sha": sha,
            "cleanup_failed": value, "stale_index": True, "index_conflict": True}}
    fields = {"result_summary": "Done", "result_data": data} if kind == "result" else {
        "success": True, "message": "Done", "payload": data}
    assert (await flow.report(task, kind, fields)).status_code == 200
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["result_data"] == {"commit_sha": sha, "claims": {
        "source": "agent_reported", "head_sha": sha, "cleanup_failed": value,
        "stale_index": True, "index_conflict": True}}
    event = next(event for event in card["events"] if event["event_type"] == kind)
    key = "result_data" if kind == "result" else "payload"
    assert event["payload"][key] == card["result_data"]


@pytest.mark.parametrize("value", ["true", 1, [], {}])
def test_cleanup_claim_is_strict_boolean(value):
    from pydantic import ValidationError
    from app.schemas.git_claims import git_claims

    with pytest.raises(ValidationError):
        git_claims({"verification": {"cleanup_failed": value}})
