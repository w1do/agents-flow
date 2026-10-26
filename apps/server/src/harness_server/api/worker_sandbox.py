"""Тонкие входы серверного учёта песочницы под отдельным worker-токеном."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from harness_shared.worker_sandbox import (
    PidIn,
    ProviderIn,
    RecoveryOut,
    SandboxState,
    StartIn,
    StartOut,
)

from harness_server.api.deps import SessionDep, require_worker_token
from harness_server.api.worker_support import TaskTokenDep, WorkerRoute
from harness_server.domain.errors import WorkerConflict
from harness_server.services import worker_sandbox as service
from harness_server.services.worker_recovery import recover

router = APIRouter(
    prefix="/worker",
    tags=["worker"],
    dependencies=[Depends(require_worker_token)],
    route_class=WorkerRoute,
)
OptionalToken = Annotated[str | None, Header(alias="X-Task-Token", max_length=512)]


def _provider(body: ProviderIn, request: Request) -> str:
    if body.provider_id != request.app.state.config.sandbox.provider_id:
        raise WorkerConflict()
    return body.provider_id


@router.post("/sandbox/recover")
async def recover_endpoint(
    body: ProviderIn, request: Request, session: SessionDep
) -> RecoveryOut | None:
    return await recover(session, _provider(body, request), request.app.state.settings)


@router.post("/tasks/{task_id}/sandbox/reserve")
async def reserve_endpoint(
    task_id: UUID, body: ProviderIn, token: TaskTokenDep, request: Request, session: SessionDep
) -> SandboxState:
    return await service.reserve(
        session,
        task_id,
        _provider(body, request),
        token,
        request.app.state.settings.harness_secret_key.get_secret_value(),
    )


@router.post("/tasks/{task_id}/sandbox/state")
async def state_endpoint(
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
    return service.state(row)


@router.post("/tasks/{task_id}/sandbox/start")
async def start_endpoint(
    task_id: UUID, body: StartIn, token: TaskTokenDep, request: Request, session: SessionDep
) -> StartOut:
    row = await service.pinned(
        session,
        task_id,
        _provider(body, request),
        token=token,
        secret_key=request.app.state.settings.harness_secret_key.get_secret_value(),
    )
    return await service.record_start(session, row, body)


@router.post("/tasks/{task_id}/sandbox/pid")
async def pid_endpoint(
    task_id: UUID, body: PidIn, request: Request, session: SessionDep, token: OptionalToken = None
) -> SandboxState:
    row = await service.pinned(
        session,
        task_id,
        _provider(body, request),
        token=token,
        secret_key=request.app.state.settings.harness_secret_key.get_secret_value(),
        cleanup=True,
    )
    return await service.record_pid(session, row, body.pid)
