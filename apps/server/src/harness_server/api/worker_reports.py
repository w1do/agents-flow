"""Тонкие входы событий, статусов, чекпоинтов и итогов worker."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from harness_shared.tasks import TaskEventOut
from harness_shared.worker_reports import CheckpointIn, EventIn, ResultIn, StatusIn

from harness_server.api.deps import SessionDep, require_worker_token
from harness_server.api.worker_support import TaskTokenDep, WorkerRoute
from harness_server.services.worker_heartbeat import heartbeat
from harness_server.services.worker_reports import report
from harness_server.wiring import secret_values

router = APIRouter(
    prefix="/worker/tasks",
    tags=["worker"],
    dependencies=[Depends(require_worker_token)],
    route_class=WorkerRoute,
)


async def _report(
    task_id: UUID, body: EventIn | CheckpointIn, token: str, request: Request, session: SessionDep
) -> TaskEventOut:
    settings = request.app.state.settings
    return await report(
        session,
        task_id,
        body,
        token=token,
        secret_key=settings.harness_secret_key.get_secret_value(),
        secrets=secret_values(settings),
    )


@router.post("/{task_id}/events")
async def events(
    task_id: UUID, body: EventIn, token: TaskTokenDep, request: Request, session: SessionDep
) -> TaskEventOut:
    return await _report(task_id, body, token, request, session)


@router.post("/{task_id}/status")
async def status(
    task_id: UUID, body: StatusIn, token: TaskTokenDep, request: Request, session: SessionDep
) -> TaskEventOut:
    return await _report(task_id, body, token, request, session)


@router.post("/{task_id}/checkpoints")
async def checkpoints(
    task_id: UUID, body: CheckpointIn, token: TaskTokenDep, request: Request, session: SessionDep
) -> TaskEventOut:
    return await _report(task_id, body, token, request, session)


@router.post("/{task_id}/result")
async def result(
    task_id: UUID, body: ResultIn, token: TaskTokenDep, request: Request, session: SessionDep
) -> TaskEventOut:
    return await _report(task_id, body, token, request, session)


@router.post("/{task_id}/heartbeat", status_code=204)
async def heartbeat_endpoint(
    task_id: UUID, token: TaskTokenDep, request: Request, session: SessionDep
) -> Response:
    await heartbeat(
        session, task_id, token, request.app.state.settings.harness_secret_key.get_secret_value()
    )
    return Response(status_code=204)
