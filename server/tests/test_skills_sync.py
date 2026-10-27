from datetime import timedelta
from uuid import uuid4

from app.repositories import AgentSkillRepository


async def test_replacement_enablement_sync_and_no_inheritance(flow):
    first, second, third = [flow.skill(name=name) for name in ("Сборка", "Тесты", "Анализ")]
    colleague, _ = flow.make_agent("Colleague")
    path = f"/agents/{flow.agent.id}/skills"
    assert (await flow.send("GET", path)).json() == []
    replacement = await flow.send("PUT", path, {"skill_ids": [str(s.id) for s in (first, second, third)],
                                                 "disabled_skill_ids": [str(third.id)]})
    assert replacement.status_code == 200
    assert all(s["assigned_at"] for s in replacement.json())
    assert sum(s["enabled"] for s in replacement.json()) == 2
    assert (await flow.send("GET", f"/agents/{colleague.id}/skills")).json() == []
    card = await flow.send("GET", f"/skills/{first.id}")
    assert card.json()["assigned_agents"] == [str(flow.agent.id)]
    sync = await flow.send("GET", path + "/sync", headers=flow.headers)
    assert len(sync.json()["skills"]) == 2
    before = replacement.json()[0]["assigned_at"]
    replaced = await flow.send("PUT", path, {"skill_ids": [str(first.id)]})
    assert len(replaced.json()) == 1
    assert replaced.json()[0]["assigned_at"] == before
    assert (await flow.send("PUT", path, {"skill_ids": []})).json() == []
    assert (await flow.send("GET", path + "/sync", headers=flow.headers)).json() == {"skills": []}


async def test_filenames_collision_and_archive(flow):
    skills = [flow.skill(name=name, category=category) for name, category in
              [("Тесты", "Разработка"), ("Testy", "Razrabotka"), ("Testy-2", "Razrabotka"),
               ("Testy", "Razrabotka")]]
    for skill in skills:
        AgentSkillRepository(flow.session).create(agent_id=flow.agent.id, skill_id=skill.id)
    flow.session.commit()
    path = f"/agents/{flow.agent.id}/skills/sync"
    files = (await flow.send("GET", path, headers=flow.headers)).json()["skills"]
    names = [s["filename"] for s in files]
    assert "razrabotka--testy.md" in names
    assert len(names) == len(set(names)) == 4
    assert all(s["name"] and s["content"] and s["content_hash"] for s in files)
    archived = await flow.send("POST", f"/skills/{skills[0].id}/archive")
    assert archived.json()["is_active"] is False
    files = (await flow.send("GET", path, headers=flow.headers)).json()["skills"]
    assert str(skills[0].id) not in [s["skill_id"] for s in files]


async def test_snapshots_survive_edits_archive_and_resume(flow, clock):
    skill = flow.skill()
    AgentSkillRepository(flow.session).create(agent_id=flow.agent.id, skill_id=skill.id)
    task = flow.task()
    original = (await flow.claim()).json()["task"]["skill_snapshots"]
    assert original[0]["skill_version"] == 1
    await flow.send("PATCH", f"/skills/{skill.id}", {"content": "New instructions"})
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["skill_snapshots"] == original
    clock[0] += timedelta(seconds=61)
    await flow.send("PATCH", f"/tasks/{task.id}", {"status": "new"})
    resumed = (await flow.claim()).json()
    assert resumed["task"]["skill_snapshots"] == original
    assert resumed["skills"][0]["version"] == original[0]["skill_version"] == 1
    assert resumed["skills"][0]["content"] == original[0]["content"] == "Run tests"
    assert resumed["skills"][0]["category"] == original[0]["category"]
    await flow.send("POST", f"/skills/{skill.id}/archive")
    assert (await flow.send("GET", f"/tasks/{task.id}")).json()["skill_snapshots"] == original


async def test_empty_first_claim_remains_empty_after_resume(flow, clock):
    task = flow.task()
    assert (await flow.claim()).json()["skills"] == []
    clock[0] += timedelta(seconds=61)
    await flow.send("PATCH", f"/tasks/{task.id}", {"status": "new"})
    skill = flow.skill()
    AgentSkillRepository(flow.session).create(agent_id=flow.agent.id, skill_id=skill.id)
    flow.session.commit()
    resumed = await flow.claim()
    assert resumed.status_code == 200
    assert resumed.json()["skills"] == []
    assert resumed.json()["task"]["skill_snapshots"] == []


async def test_sync_and_assignment_errors_are_atomic(flow):
    skill = flow.skill()
    path = f"/agents/{flow.agent.id}/skills"
    assert (await flow.send("PUT", path, {"skill_ids": [str(skill.id), str(uuid4())]})).status_code == 404
    assert (await flow.send("GET", path)).json() == []
    assert (await flow.send("PUT", path, {"skill_ids": [str(skill.id)] * 2})).status_code == 422
    assert (await flow.send("GET", f"/agents/{uuid4()}/skills/sync", headers=flow.headers)).status_code == 404
    assert (await flow.send("GET", path + "/sync")).status_code == 403
    assert (await flow.send("PUT", f"/agents/{uuid4()}/skills", {"skill_ids": []})).status_code == 404


async def test_next_task_snapshot_gets_current_version(flow, clock):
    skill = flow.skill()
    AgentSkillRepository(flow.session).create(agent_id=flow.agent.id, skill_id=skill.id)
    first = flow.task()
    await flow.claim()
    await flow.send("PATCH", f"/skills/{skill.id}", {"content": "Updated"})
    await flow.report(first, "fail", {"message": "Stopped"})
    second = flow.task()
    response = await flow.claim()
    assert response.json()["task"]["id"] == str(second.id)
    assert response.json()["task"]["skill_snapshots"][0]["skill_version"] == 2
    original = (await flow.send("GET", f"/tasks/{first.id}")).json()["skill_snapshots"]
    assert original[0]["skill_version"] == 1


async def test_secret_fragments_are_warned_and_hash_matches_original_content(flow):
    from hashlib import sha256

    skill = flow.skill()
    token = "ghp_" + "x" * 36
    changed = await flow.send("PATCH", f"/skills/{skill.id}", {"content": "Token: " + token})
    assert changed.json()["warnings"]
    assert token in skill.content
    AgentSkillRepository(flow.session).create(agent_id=flow.agent.id, skill_id=skill.id)
    flow.session.commit()
    sync = await flow.send("GET", f"/agents/{flow.agent.id}/skills/sync", headers=flow.headers)
    item = sync.json()["skills"][0]
    assert token in sync.text
    assert item["content_hash"] == sha256(item["content"].encode()).hexdigest()
    repeated = await flow.send("PATCH", f"/skills/{skill.id}", {"content": "Token: " + token})
    assert repeated.json()["version"] == changed.json()["version"]
