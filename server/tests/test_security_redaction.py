from sqlalchemy import select

from app.models import IdempotencyKey, Task, TaskSkillSnapshot
from app.repositories import AgentSkillRepository
from app.repositories.task_skill_snapshot import TaskSkillSnapshotRepository
from app.services.agent_auth import generate_agent_token
from app.services.skill_content import redact


def test_shared_secret_detector_covers_provider_formats():
    values = ["github_pat_" + "a" * 24, "ghp_" + "a" * 36, "gho_" + "a" * 24,
              "ghu_" + "a" * 24, "ghs_" + "a" * 24, "sk-proj-" + "a" * 24,
              "AKIA" + "A" * 16, "xoxb-" + "a" * 24]
    agent_token, _ = generate_agent_token()
    assert all("[REDACTED]" in redact(value) for value in [*values, agent_token])


async def test_report_event_ids_share_secret_detector(flow):
    task = flow.task("active", leased=True)
    for secret in ("AKIA" + "A" * 16, "ghp_" + "A" * 36):
        response = await flow.report(task, "events", {"event_type": "progress", "message": "ok"},
                                     event_id=secret)
        assert response.status_code == 422 and secret not in response.text
    valid = await flow.report(task, "events", {"event_type": "progress", "message": "ok"},
                              event_id="event_valid-1")
    assert valid.status_code == 200 and valid.json()["event_id"] == "event_valid-1"


async def test_task_fields_are_redacted_in_storage_card_and_idempotency(flow):
    secret = "ghp_" + "A" * 36
    body = {"title": f"title {secret}", "description": f"description {secret}",
            "source_type": "api", "source_text": f"source {secret}"}
    response = await flow.send("POST", f"/projects/{flow.project.id}/tasks", body, key="task-safe")
    assert response.status_code == 201 and secret not in response.text
    task = flow.session.scalar(select(Task))
    assert secret not in str((task.title, task.description, task.source_text))
    stored = flow.session.scalar(select(IdempotencyKey).where(
        IdempotencyKey.idempotency_key == "task-safe"))
    assert secret not in str(stored.response_body)
    assert (await flow.send("GET", f"/tasks/{task.id}")).status_code == 200


async def test_decision_feedback_is_redacted_in_card_and_execution_state(flow):
    secret = "ghp_" + "B" * 36
    task = flow.task("backlog", leased=True)
    plan = await flow.send("POST", f"/tasks/{task.id}/plan/decision",
                           {"decision": "rejected", "feedback": secret}, key="plan-safe")
    assert plan.status_code == 200 and secret not in plan.text
    assert secret not in task.plan_feedback
    assert secret not in (await flow.state(task)).text
    assert secret not in (await flow.send("GET", f"/tasks/{task.id}")).text
    result_secret = "ghp_" + "E" * 36
    ready = flow.task("ready", leased=True)
    result = await flow.send("POST", f"/tasks/{ready.id}/result/decision",
                             {"decision": "rework", "feedback": result_secret}, key="result-safe")
    assert result.status_code == 200 and result_secret not in result.text
    assert result_secret not in (await flow.state(ready)).text


async def test_skill_secret_is_redacted_only_in_task_snapshot_and_claim(flow):
    secret = "ghp_" + "C" * 36
    skill = flow.skill(content=f"Instructions: {secret}")
    AgentSkillRepository(flow.session).create(agent_id=flow.agent.id, skill_id=skill.id)
    task = flow.task()
    claim = await flow.claim(key="claim-secret")
    assert claim.status_code == 200 and secret not in claim.text
    assert secret in skill.content
    assert secret not in flow.session.scalar(select(TaskSkillSnapshot)).content
    sync = await flow.send("GET", f"/agents/{flow.agent.id}/skills/sync", headers=flow.headers)
    assert secret in sync.text


async def test_legacy_snapshot_missing_flag_reaches_claim(flow):
    skill = flow.skill()
    task = flow.task()
    TaskSkillSnapshotRepository(flow.session).create(
        task_id=task.id, skill_id=skill.id, skill_name=skill.name, category="Legacy",
        skill_version=1, content_hash="old-hash", content="", content_missing=True, filename=None,
    )
    flow.session.commit()
    claim = await flow.claim()
    assert claim.status_code == 200
    assert claim.json()["skills"][0]["snapshot_content_missing"] is True


async def test_idempotency_key_is_trimmed_validated_and_deduplicated(flow):
    body = {"title": "Task", "description": "Work", "source_type": "api", "source_text": "Task"}
    path = f"/projects/{flow.project.id}/tasks"
    assert (await flow.send("POST", path, body, key="   ")).status_code == 422
    token, _ = generate_agent_token()
    assert (await flow.send("POST", path, body, key=token)).status_code == 422
    first = await flow.send("POST", path, body, key="  dedupe-1  ")
    repeated = await flow.send("POST", path, body, key="dedupe-1")
    assert first.status_code == repeated.status_code == 201
    assert first.content == repeated.content


async def test_validation_error_does_not_return_secret_in_extra_field_name(flow):
    secret = "ghp_" + "D" * 36
    body = {"title": "Task", "description": "Work", "source_type": "api",
            "source_text": "Task", secret: secret}
    response = await flow.send("POST", f"/projects/{flow.project.id}/tasks", body)
    assert response.status_code == 422 and secret not in response.text


async def test_server_event_types_are_forbidden(flow):
    for event_type in ("publication-result", "claimed", "created", "status", "decision",
                       "lease-claimed", "lease-expired", "lease-extended", "lease-renewed",
                       "stalled", "merged", "paused", "trash", "error", "plan_decision",
                       "result_decision", "lease_expired", "status_changed", "status-changed",
                       "status-updated", "status-", "status_", "lease-", "lease_",
                       "status-progress", "status_custom", "lease-custom", "lease_custom"):
        task = flow.task("active", leased=True)
        response = await flow.report(task, "events", {"event_type": event_type, "message": "Fake"})
        assert response.status_code == 403, event_type


async def test_user_event_types_are_accepted(flow):
    for event_type in ("tests", "test_results", "checkpoint", "result", "progress", "planning",
                       "testing", "build.started", "Tests"):
        status = "choosing" if event_type == "planning" else "active"
        task = flow.task(status, leased=True)
        response = await flow.report(task, "events", {"event_type": event_type, "message": "Update"})
        assert response.status_code == 200, event_type


async def test_event_type_format_is_validated(flow):
    for event_type in ("", "a" * 129, "contains-ghp_" + "A" * 36):
        task = flow.task("active", leased=True)
        response = await flow.report(task, "events", {"event_type": event_type, "message": "Update"})
        assert response.status_code == 422, event_type


async def test_long_user_event_type_is_accepted(flow):
    task = flow.task("active", leased=True)
    response = await flow.report(task, "events", {"event_type": "a" * 65, "message": "Update"})
    assert response.status_code == 200
