"""HTTP-вход задач: POST /tasks и GET /tasks/{id}. Только разбор запроса и вызов services.tasks.

Авторизация — router-зависимость: она выполняется раньше валидации тела и path-параметров, поэтому
запрос без токена получает 401 независимо от содержимого (проверяется тестом).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from harness_shared.tasks import (
    TaskCreateIn,
    TaskDetailOut,
    TaskEventOut,
    TaskKind,
    TaskOut,
    TaskSource,
)

from harness_server.api.deps import ConfigDep, SessionDep, require_admin_token
from harness_server.domain.errors import NotFound, UnknownWorkspace
from harness_server.services.tasks import create_task, get_task, list_task_events

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(require_admin_token)])


@router.post("", status_code=201, response_model=TaskOut)
async def create_task_endpoint(
    body: TaskCreateIn, session: SessionDep, config: ConfigDep
) -> TaskOut:
    """Создаёт задачу plan в статусе new с источником api (D-25)."""
    try:
        task = await create_task(
            session,
            kind=TaskKind.PLAN,
            text=body.text,
            source=TaskSource.API,
            workspace_id=body.workspace_id,
            known_workspace_ids=[workspace.id for workspace in config.workspaces],
        )
    except UnknownWorkspace:
        raise HTTPException(status_code=422, detail="unknown_workspace") from None
    return TaskOut.model_validate(task)


@router.get("/{task_id}", response_model=TaskDetailOut)
async def get_task_endpoint(task_id: UUID, session: SessionDep) -> TaskDetailOut:
    """Задача вместе с лентой событий."""
    try:
        task = await get_task(session, task_id)
        events = await list_task_events(session, task_id)
    except NotFound:
        raise HTTPException(status_code=404, detail="not_found") from None
    return TaskDetailOut(
        **TaskOut.model_validate(task).model_dump(),
        events=[TaskEventOut.model_validate(event) for event in events],
    )
