"""Size and protected-text regressions at the report HTTP boundary."""
import json

import pytest

from app.schemas.git_claims import git_claims, relative_path
from app.services.skill_content import sanitize


@pytest.mark.parametrize("name", [".Secrets", ".SECRETS", "key.PEM", ".NPMRC"])
def test_casefolded_claim_path_and_text(name):
    with pytest.raises(ValueError):
        relative_path("src/" + name + "/fixture")
    assert name not in sanitize({"subject": "read src/" + name + "/fixture"})["subject"]


def test_subject_limit_also_holds_after_redaction_expands_text():
    text = ".env " * 40
    data = git_claims({"commit_subject": text, "claims": {
        "commits": [{"sha": "b" * 40, "subject": text}]}})
    for subject in (data["commit_subject"], data["claims"]["commits"][0]["subject"]):
        assert len(subject) <= 200
        assert ".env" not in subject


@pytest.mark.parametrize("kind", ["result", "publication-result", "events", "fail"])
@pytest.mark.parametrize("data", [
    {"changed_paths": ["a"] * 1001}, {"commit_subject": "x" * 201},
    {"extra": "x" * (256 * 1024)}, {"extra": "я" * (128 * 1024)},
])
async def test_oversized_payload_returns_422(flow, kind, data):
    task = flow.task("merged" if kind == "publication-result" else "testing", leased=True)
    fields = {"result_summary": "done", "result_data": data} if kind == "result" else {
        "message": "done", "payload": data}
    if kind == "publication-result":
        fields["success"] = True
    if kind == "events":
        fields["event_type"] = "progress"
    response = await flow.report(task, kind, fields)
    assert response.status_code == 422
    assert "x" * 201 not in response.text


async def test_request_body_limit_applies_before_json_parsing(flow):
    task = flow.task("testing", leased=True)
    response = await flow.report(task, "result", {"result_summary": "x" * (512 * 1024), "result_data": {}})
    assert response.status_code == 422


async def test_merged_publication_payload_is_bounded(flow):
    task = flow.task("merged", leased=True, result_data={"old": "a" * (200 * 1024)})
    response = await flow.report(task, "publication-result", {
        "success": True, "message": "done", "payload": {"new": "b" * (100 * 1024)}})
    assert response.status_code == 422
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert "new" not in card["result_data"]


async def test_valid_payload_limits_are_accepted(flow):
    task = flow.task("testing", leased=True)
    response = await flow.report(task, "result", {"result_summary": "done", "result_data": {
        "commit_subject": "a" * 200, "changed_paths": ["a"] * 1000, "extra": "b" * (200 * 1024)}})
    assert response.status_code == 200


@pytest.mark.parametrize("kind", ["result", "publication-result", "events", "fail"])
async def test_protected_free_text_never_reaches_events(flow, kind):
    task = flow.task("merged" if kind == "publication-result" else "testing", leased=True)
    text = "read .Secrets/hidden-fixture and key.PEM and .NPMRC"
    data = {"commit_subject": text, "claims": {"commits": [{"sha": "b" * 40, "subject": text}]}}
    fields = {"result_summary": text, "result_data": data} if kind == "result" else {
        "message": text, "payload": data}
    if kind == "publication-result":
        fields["success"] = True
    if kind == "events":
        fields["event_type"] = "progress"
    assert (await flow.report(task, kind, fields)).status_code == 200
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    serialized = json.dumps(card)
    for name in (".Secrets", "hidden-fixture", "key.PEM", ".NPMRC"):
        assert name not in serialized
    assert "[REDACTED]" in serialized
