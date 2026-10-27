from fastapi import HTTPException

from app.repositories.task_history import TaskHistory
from app.services import tasks
from app.services.leases import release
from app.services.task_status import transition


def decide(session, task_id, kind, body):
    task = tasks.get_task(session, task_id, lock=True)
    required = "backlog" if kind == "plan" else "ready"
    if task.status != required:
        raise HTTPException(409, "Invalid task transition")
    targets = {"approved": "active", "rejected": "planning", "trash": "trash",
               "publish": "merged", "rework": "active", "keep_ready": "ready"}
    transition(task, targets[body.decision], "admin")
    if kind == "plan" and body.decision != "trash":
        task.plan_decision, task.plan_feedback = body.decision, body.feedback
        if body.decision == "rejected":
            task.plan_revision += 1
    if body.decision == "trash":
        release(session, task, clear=True)
    TaskHistory(session).append(task.id, f"{kind}_decision", "Решение администратора",
                                payload=body.model_dump())
    return tasks.card(session, task)
