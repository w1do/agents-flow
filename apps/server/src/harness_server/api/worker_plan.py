"""Тонкие входы состояния и завершения плана."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from harness_shared.planning import PlanFinishIn, PlanState
from harness_shared.tasks import TaskEventOut

from harness_server.api.deps import SessionDep, require_worker_token
from harness_server.api.worker_support import TaskTokenDep, WorkerRoute
from harness_server.services.notify import plan_ready
from harness_server.services.plan_result import finish, read_state
from harness_server.services.worker_access import authorize_task
from harness_server.wiring import secret_values

router = APIRouter(
    prefix="/worker/tasks",
    dependencies=[Depends(require_worker_token)],
    route_class=WorkerRoute,
)


@router.post("/{task_id}/plan/state")
async def state(
    task_id: UUID,
    token: TaskTokenDep,
    request: Request,
    session: SessionDep,
) -> PlanState:
    settings = request.app.state.settings
    task = await authorize_task(
        session, task_id, token, settings.harness_secret_key.get_secret_value()
    )
    return await read_state(session, task, (*secret_values(settings), token))


@router.post("/{task_id}/plan/finish")
async def finish_plan(
    task_id: UUID,
    body: PlanFinishIn,
    token: TaskTokenDep,
    request: Request,
    session: SessionDep,
) -> TaskEventOut:
    settings = request.app.state.settings
    event = await finish(
        session,
        task_id,
        body,
        token=token,
        secret_key=settings.harness_secret_key.get_secret_value(),
        secrets=secret_values(settings),
    )
    if body.status == "ready":
        await plan_ready(request.app.state.bot, task_id)
    return event
