"""Round 4 report limits and precise protected-path redaction."""
import pytest

from app.services.skill_content import sanitize


@pytest.mark.parametrize("value", ["Fix KeyboardEvent.key handling", {"event.key": "Enter"},
                                    "const key = event.key;"])
def test_identifiers_remain_unchanged(value):
    assert sanitize(value) == value


@pytest.mark.parametrize("text", ["key.PEM?marker=42", "src/key.PEM?marker=42,next",
                                   "src/private.key?marker=42",
                                   "key.PEM?token=[REDACTED]&marker=42",
                                   ".secrets/x?marker=42;next", '".NPMRC?marker=42" next'])
def test_protected_token_tail_is_masked(text):
    assert "42" not in sanitize(text)
    assert "[REDACTED]" in sanitize(text)


@pytest.mark.parametrize("event_id", ["key.PEM", ".NPMRC", ".secrets"])
async def test_protected_event_id_is_rejected(flow, event_id):
    task = flow.task("testing", leased=True)
    response = await flow.report(task, "events", {"event_type": "progress", "message": "ok"},
                                 event_id=event_id)
    assert response.status_code == 422
    assert event_id not in response.text


@pytest.mark.parametrize("kind", ["result", "events", "fail", "publication-result"])
async def test_payload_depth_returns_422(flow, kind):
    task = flow.task("merged" if kind == "publication-result" else "testing", leased=True)
    nested = {}
    for _ in range(40):
        nested = {"nested": nested}
    fields = {"result_summary": "done", "result_data": nested} if kind == "result" else {
        "message": "done", "payload": nested}
    if kind == "events":
        fields["event_type"] = "progress"
    if kind == "publication-result":
        fields["success"] = True
    assert (await flow.report(task, kind, fields)).status_code == 422


@pytest.mark.parametrize("kind", ["events", "fail"])
async def test_sanitized_payload_size_is_rechecked(flow, kind):
    task = flow.task("testing", leased=True)
    fields = {"message": "done", "payload": {"text": ".env " * 26000}}
    if kind == "events":
        fields["event_type"] = "progress"
    assert (await flow.report(task, kind, fields)).status_code == 422


async def test_maximum_payload_depth_is_accepted(flow):
    nested = {}
    for _ in range(32):
        nested = {"nested": nested}
    task = flow.task("testing", leased=True)
    response = await flow.report(task, "result", {"result_summary": "done", "result_data": nested})
    assert response.status_code == 200


async def test_checkpoint_depth_is_bounded(flow):
    nested = []
    for _ in range(33):
        nested = [nested]
    task = flow.task("testing", leased=True)
    response = await flow.report(task, "events", {
        "event_type": "progress", "message": "done", "checkpoint": {"nested": nested}})
    assert response.status_code == 422


def test_schema_rejects_deep_payload_without_http_middleware():
    from uuid import uuid4
    from pydantic import ValidationError
    from app.schemas.reports import FailRequest

    nested = {}
    for _ in range(33):
        nested = {"nested": nested}
    with pytest.raises(ValidationError, match="nesting limit"):
        FailRequest(lease_id=uuid4(), event_id="fixture", message="done", payload=nested)


def test_index_conflict_flags_remain_unverified_claims():
    from app.schemas.git_claims import git_claims

    data = git_claims({"verification": {"stale_index": True, "index_conflict": True, "worktree_clean": False}})
    assert data["claims"] == {"source": "agent_reported", "stale_index": True,
                              "index_conflict": True, "worktree_clean": False}
