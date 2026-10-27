"""A keep-ready decision starts a fresh round of result buttons and feedback."""
from sqlalchemy import select

from app.models import TaskEvent


def current(session, task_id, kind):
    latest = session.scalar(select(TaskEvent).where(TaskEvent.task_id == task_id,
        TaskEvent.event_type.in_((kind, f"{kind}_decision")))
        .order_by(TaskEvent.created_at.desc()).limit(1))
    if latest and (latest.event_type == kind or
                   (kind == "result" and (latest.payload or {}).get("decision") == "keep_ready")):
        return latest
    return None
