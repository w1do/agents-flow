from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_bytes

import bcrypt

from app import repositories as repos


def entity_values(session, name):
    def create(kind):
        repository = getattr(repos, f"{kind}Repository")(session)
        values, _ = entity_values(session, kind)
        return repository.create(**values)

    digest = sha256(b"test content").hexdigest()
    if name == "User":
        password_hash = bcrypt.hashpw(token_bytes(24), bcrypt.gensalt(rounds=4)).decode()
        return {"email": "admin@example.test", "password_hash": password_hash}, {"email": "new@example.test"}
    if name == "Project":
        return {"name": "Demo"}, {"name": "Updated"}
    if name == "SkillCategory":
        return {"name": "Development", "description": "Tools"}, {"sort_order": 5}
    if name == "IdempotencyKey":
        return {"scope": "projects", "idempotency_key": "request-1", "request_hash": digest,
                "response_code": 201, "response_body": {"id": "demo"}}, {"response_body": {"ok": True}}
    if name == "ProjectInitToken":
        return {"project_id": create("Project").id, "token_hash": digest,
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)}, {"token_hash": "changed"}
    if name == "Agent":
        return {"project_id": create("Project").id, "name": "worker", "agent_token_hash": digest,
                "repository_path_hint": "/tmp/demo", "git_remote": "origin"}, {"status": "online"}
    if name == "Skill":
        return {"category_id": create("SkillCategory").id, "name": "Build", "description": "Build app",
                "content": "Run build", "content_hash": digest}, {"version": 2}
    if name == "AgentSkill":
        return {"agent_id": create("Agent").id, "skill_id": create("Skill").id}, {"enabled": False}
    if name == "Task":
        return {"project_id": create("Project").id, "title": "Fix", "description": "Fix bug",
                "source_type": "api", "source_text": "Fix bug"}, {"checkpoint": {"step": 1}, "status": "planning"}
    if name == "TaskSkillSnapshot":
        return {"task_id": create("Task").id, "skill_id": create("Skill").id, "skill_name": "Build",
                "skill_version": 1, "content_hash": digest}, {"skill_name": "Recorded"}
    if name == "TaskEvent":
        return {"task_id": create("Task").id, "event_type": "progress", "message": "Started",
                "event_id": "event-1", "payload": {"step": 1}}, {"payload": {"step": 2}}
    raise ValueError(name)
