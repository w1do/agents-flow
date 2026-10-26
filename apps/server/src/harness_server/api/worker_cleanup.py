"""Начало и завершение очистки: токены отзываются до локальных команд."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from harness_shared.worker_sandbox import CleanupIn, ProviderIn, SandboxState

from harness_server.api.deps import SessionDep, require_worker_token
from harness_server.api.worker_sandbox import OptionalToken, _provider
from harness_server.api.worker_support import WorkerRoute
from harness_server.services import worker_sandbox as service

router = APIRouter(
    prefix="/worker",
    tags=["worker"],
    dependencies=[Depends(require_worker_token)],
    route_class=WorkerRoute,
)


@router.post("/tasks/{task_id}/sandbox/cleanup")
async def cleanup_endpoint(
    task_id: UUID,
    body: ProviderIn,
    request: Request,
    session: SessionDep,
    token: OptionalToken = None,
) -> SandboxState:
    row = await service.pinned(
        session,
        task_id,
        _provider(body, request),
        token=token,
        secret_key=request.app.state.settings.harness_secret_key.get_secret_value(),
        cleanup=True,
    )
    return await service.begin_cleanup(session, row)


@router.post("/tasks/{task_id}/sandbox/release", status_code=204)
async def release_endpoint(
    task_id: UUID,
    body: CleanupIn,
    request: Request,
    session: SessionDep,
    token: OptionalToken = None,
) -> Response:
    row = await service.pinned(
        session,
        task_id,
        _provider(body, request),
        token=token,
        secret_key=request.app.state.settings.harness_secret_key.get_secret_value(),
        cleanup=True,
        released=True,
    )
    await service.finish_cleanup(session, row, body.success)
    return Response(status_code=204)
