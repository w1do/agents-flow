from fastapi import HTTPException

from app.core import time
from app.repositories.task_history import TaskHistory
from app.schemas.reports import ReportResponse
from app.schemas.tasks import ExecutionStateResponse
from app.services.leases import agent_task, release
from app.services.task_status import transition
from app.services.skill_content import redact
from app.services.report_event_types import is_reserved_event


def _apply(task, kind, body):
    if kind == "plan":
        transition(task, "backlog", "agent_plan")
        task.plan_text, task.plan_decision = body.plan_text, "pending"
    elif kind == "result":
        transition(task, "ready", "agent_result")
        task.result_summary, task.result_data = body.result_summary, body.result_data
    elif kind == "fail":
        transition(task, "error", "agent_fail")
    elif kind == "publication-result":
        if task.status != "merged":
            raise HTTPException(409, "Publication is not authorized")
        task.completed_at = time.now()
    elif kind == "events":
        target = (body.payload or {}).get("status")
        if target is None and body.event_type in {"planning", "testing"}:
            target = body.event_type
        if target is not None:
            transition(task, target, "agent")
        if body.checkpoint is not None:
            task.checkpoint = body.checkpoint


def report(session, task_id, agent, kind, body):
    task = agent_task(session, task_id, agent, body.lease_id)
    history = TaskHistory(session)
    if history.event(task.id, body.event_id):
        return ReportResponse(task_id=task.id, status=task.status, event_id=body.event_id)
    if task.status == "error" or task.completed_at:
        raise HTTPException(409, "Task is finished")
    values = body.model_dump(mode="json", exclude={"lease_id", "event_id"})
    if kind == "events" and _reserved_event(body.event_type):
        raise HTTPException(403, "Reserved event type")
    values = _sanitize(values)
    safe_body = body.model_copy(update=values)
    _apply(task, kind, safe_body)
    message = values.get("message", values.get("plan_text", values.get("result_summary", kind)))
    history.append(task.id, safe_body.event_type if kind == "events" else kind, message,
                   agent_id=agent.id, event_id=body.event_id, payload=values)
    if kind in {"fail", "publication-result"}:
        release(session, task)
    session.flush()
    return ReportResponse(task_id=task.id, status=task.status, event_id=body.event_id)


def execution_state(session, task_id, agent, lease_id):
    task = agent_task(session, task_id, agent, lease_id)
    events = TaskHistory(session).events(task.id)
    decisions = [event.payload for event in events if event.event_type == "result_decision"]
    last = decisions[-1] if decisions else {}
    published = any(event.event_type == "publication-result" and event.agent_id is not None
                    for event in events)
    return ExecutionStateResponse(
        task_id=task.id, status=task.status, plan_decision=task.plan_decision,
        plan_revision=task.plan_revision, plan_feedback=task.plan_feedback,
        result_feedback=last.get("feedback"),
        publication_requested=last.get("decision") == "publish" and not published,
        lease_id=task.lease_id, lease_expires_at=time.as_utc(task.lease_expires_at),
        checkpoint=task.checkpoint,
    )


def _reserved_event(event_type):
    return is_reserved_event(event_type)


def _sanitize(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {redact(key) if isinstance(key, str) else key: _sanitize(item)
                for key, item in value.items()}
    return value
