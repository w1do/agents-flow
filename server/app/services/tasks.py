from app.core import time
from app.core.errors import not_found
from app.repositories.task import TaskRepository
from app.repositories.task_history import TaskHistory
from app.schemas.tasks import TaskEventResponse, TaskResponse, TaskSkillSnapshotResponse
from app.services.projects import get_project
from app.services.task_status import transition
from app.services.skill_content import redact


def get_task(session, task_id, *, lock=False):
    repo = TaskRepository(session)
    task = repo.lock(task_id) if lock else repo.get(task_id)
    if task is None:
        raise not_found()
    return task


def card(session, task):
    session.flush()
    response = TaskResponse.model_validate(task)
    for key in ("created_at", "updated_at", "lease_expires_at", "completed_at"):
        value = getattr(response, key)
        if value is not None:
            setattr(response, key, time.as_utc(value))
    history = TaskHistory(session)
    response.events = [TaskEventResponse.model_validate(event) for event in history.events(task.id)]
    for event in response.events:
        event.created_at = time.as_utc(event.created_at)
    response.skill_snapshots = [TaskSkillSnapshotResponse.model_validate(row)
                               for row in history.snapshots(task.id)]
    return response


def create(session, project_id, body):
    get_project(session, project_id)
    values = {key: redact(value) if isinstance(value, str) else value
              for key, value in body.model_dump().items()}
    task = TaskRepository(session).create(project_id=project_id, **values)
    TaskHistory(session).append(task.id, "created", "Задача создана")
    return card(session, task)


def listing(session, project_id, status=None, offset=0, limit=50):
    get_project(session, project_id)
    return [card(session, task) for task in TaskRepository(session).for_project(
        project_id, status, offset, limit,
    )]


def change_status(session, task_id, body):
    task = get_task(session, task_id, lock=True)
    transition(task, body.status, "admin")
    TaskHistory(session).append(task.id, "status", "Статус изменён администратором",
                                payload={"status": body.status})
    if body.status in {"new", "paused", "trash"}:
        from app.services.leases import release

        release(session, task, clear=True)
    return card(session, task)
