from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException

from app.core import time
from app.core.errors import not_found
from app.core.task_states import WORKING
from app.repositories.agent import AgentRepository
from app.repositories.task import TaskRepository
from app.repositories.task_history import TaskHistory
from app.schemas.leases import ClaimResponse, HeartbeatResponse
from app.services import skills, tasks
from app.services.task_status import transition
from app.services.skill_content import content_values, redact, unique_filename


def validate_lease(task, agent, lease_id):
    if (task.assigned_agent_id != agent.id or task.lease_id != lease_id
            or task.status in {"stalled", "paused", "trash", "new"}
            or task.lease_expires_at is None
            or time.as_utc(task.lease_expires_at) <= time.now()):
        raise HTTPException(409, "Invalid lease")


def agent_task(session, task_id, agent, lease_id):
    task = tasks.get_task(session, task_id, lock=True)
    if task.project_id != agent.project_id:
        raise not_found()
    validate_lease(task, agent, lease_id)
    return task


def release(session, task, clear=False):
    if task.assigned_agent_id:
        agent = AgentRepository(session).lock(task.assigned_agent_id)
        agent.status = "online"
    if clear:
        task.lease_id, task.lease_expires_at = None, None


def claim(session, agent):
    agent = AgentRepository(session).lock(agent.id)
    if TaskRepository(session).leased(agent.id):
        raise HTTPException(409, "Agent is busy")
    task = TaskRepository(session).next_new(agent.project_id)
    if task is None:
        return None
    task.assigned_agent_id, task.lease_id = agent.id, uuid4()
    task.lease_expires_at = time.now() + timedelta(seconds=time.lease_ttl_seconds())
    transition(task, "choosing")
    agent.status, agent.last_heartbeat_at = "busy", time.now()
    history = TaskHistory(session)
    snapshots = history.snapshots(task.id)
    if snapshots or history.was_claimed(task.id):
        files = _snapshot_files(snapshots)
    else:
        files = _safe_skill_files(skills.sync(session, agent.id)["skills"])
        history.snapshot(task.id, files)
    TaskHistory(session).append(task.id, "claimed", "Задача арендована", agent_id=agent.id)
    return ClaimResponse(task=tasks.card(session, task), skills=files, lease_id=task.lease_id,
                         lease_expires_at=task.lease_expires_at)


def _safe_skill_files(files):
    return [skill.model_copy(update=content_values(redact(skill.content))) for skill in files]


def _snapshot_files(snapshots):
    files, used = [], set()
    ordered = sorted(snapshots, key=lambda item: str(item.skill_id))
    for snapshot in ordered:
        filename = snapshot.filename or unique_filename(snapshot.category, snapshot.skill_name, used)
        used.add(filename)
        files.append({"skill_id": snapshot.skill_id, "category": snapshot.category,
                      "name": snapshot.skill_name, "filename": filename,
                      "version": snapshot.skill_version, "content_hash": snapshot.content_hash,
                      "content": snapshot.content,
                      "snapshot_content_missing": snapshot.content_missing})
    return files


def heartbeat(session, agent, body):
    if body.task_id is not None:
        task = agent_task(session, body.task_id, agent, body.lease_id)
        if task.status not in WORKING | {"merged"} or task.completed_at:
            raise HTTPException(409, "Task is finished")
        task.lease_expires_at = time.now() + timedelta(seconds=time.lease_ttl_seconds())
        agent.status = "busy"
        expires = task.lease_expires_at
    else:
        agent = AgentRepository(session).lock(agent.id)
        active = TaskRepository(session).leased(agent.id)
        agent.status = "busy" if active else "online"
        expires = time.as_utc(active[0].lease_expires_at) if active else None
    agent.last_heartbeat_at = time.now()
    return HeartbeatResponse(status=agent.status, lease_expires_at=expires)
