"""Тонкий HTTP-вход worker с отдельной авторизацией."""

from fastapi import APIRouter, Depends, Request
from harness_shared.worker import ClaimIn, ClaimOut

from harness_server.api.deps import SessionDep, require_worker_token
from harness_server.api.worker_support import WorkerRoute
from harness_server.services.worker_queue import claim

router = APIRouter(
    prefix="/worker",
    tags=["worker"],
    dependencies=[Depends(require_worker_token)],
    route_class=WorkerRoute,
)


@router.post("/tasks/claim")
async def claim_task(body: ClaimIn, request: Request, session: SessionDep) -> ClaimOut | None:
    """Следующая доступная задача; JSON null при пустой очереди."""
    return await claim(session, body, request.app.state.settings, request.app.state.config)
