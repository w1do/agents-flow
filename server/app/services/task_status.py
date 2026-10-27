from fastapi import HTTPException

from app.core.task_states import STATUSES, WORKING

TRANSITIONS = {
    "new": {"choosing", "paused", "trash"},
    "choosing": {"planning", "paused", "trash", "error", "stalled"},
    "planning": {"backlog", "paused", "trash", "error", "stalled"},
    "backlog": {"active", "planning", "paused", "trash", "error", "stalled"},
    "active": {"testing", "paused", "trash", "error", "stalled"},
    "testing": {"ready", "paused", "trash", "error", "stalled"},
    "ready": {"merged", "active", "ready", "paused", "trash", "error", "stalled"},
    "merged": {"trash"}, "error": {"trash"}, "stalled": {"new", "trash"},
    "paused": {"trash"}, "trash": {"trash"},
}


def validate_transition(current: str, target: str, actor: str = "server") -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise HTTPException(409, "Invalid task transition")
    if actor == "agent" and (current in {"backlog", "ready"} or target in {
            "stalled", "merged", "paused", "trash", "error", "backlog", "active", "ready"}):
        raise HTTPException(403, "Forbidden")
    if actor == "agent_plan" and (current, target) != ("planning", "backlog"):
        raise HTTPException(403, "Forbidden")
    if actor == "agent_result" and (current, target) != ("testing", "ready"):
        raise HTTPException(403, "Forbidden")
    if actor == "agent_fail" and target != "error":
        raise HTTPException(403, "Forbidden")
    if current == "stalled" and target == "new" and actor != "admin":
        raise HTTPException(403, "Forbidden")


def transition(task, target: str, actor: str = "server") -> None:
    validate_transition(task.status, target, actor)
    task.status = target
