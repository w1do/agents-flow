from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Database
from app.api.flow_deps import Write, flow_admin
from app.schemas.tasks import TaskCreate, TaskPatch, TaskResponse, TaskStatus
from app.services import tasks

router = APIRouter(tags=["tasks"], dependencies=[Depends(flow_admin)])


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse, status_code=201)
def create(project_id: UUID, body: TaskCreate, session: Database, write: Write):
    return write.run(body, lambda: tasks.create(session, project_id, body), status=201)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskResponse])
def listing(project_id: UUID, session: Database, status: TaskStatus | None = None,
            offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    return tasks.listing(session, project_id, status, offset, limit)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get(task_id: UUID, session: Database):
    return tasks.card(session, tasks.get_task(session, task_id))


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def patch(task_id: UUID, body: TaskPatch, session: Database, write: Write):
    return write.run(body, lambda: tasks.change_status(session, task_id, body))
