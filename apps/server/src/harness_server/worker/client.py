"""Типизированный клиент worker; сеть изолирована адаптером, БД здесь нет."""

from uuid import UUID

from harness_shared.planning import PlanFinishIn, PlanState
from harness_shared.tasks import TaskEventOut, TaskKind
from harness_shared.worker import ClaimIn, ClaimOut
from harness_shared.worker_reports import CheckpointIn, EventIn
from harness_shared.worker_sandbox import ProviderIn, RecoveryOut, SandboxState
from pydantic import BaseModel, ValidationError

from harness_server.adapters.worker_api import WorkerAPI, WorkerAPIError


def parse[T: BaseModel](model: type[T], data: object) -> T:
    """Ошибки схемы не содержат входные значения или секреты."""
    try:
        return model.model_validate(data)
    except ValidationError:
        raise WorkerAPIError("invalid_response") from None


class WorkerClient:
    """DTO на границе; сервер определяет очередь, роли, переходы и состояние песочницы."""

    def __init__(self, api: WorkerAPI) -> None:
        self.api = api

    async def plan_state(self, task_id: UUID, token: str) -> PlanState:
        return parse(
            PlanState,
            await self.api.post(
                f"/worker/tasks/{task_id}/plan/state",
                token=token,
            ),
        )

    async def plan_finish(self, task_id: UUID, body: PlanFinishIn, token: str) -> TaskEventOut:
        return parse(
            TaskEventOut,
            await self.api.post(
                f"/worker/tasks/{task_id}/plan/finish",
                body,
                token=token,
            ),
        )

    async def claim(self, kind: TaskKind, provider_id: str) -> ClaimOut | None:
        data = await self.api.post(
            "/worker/tasks/claim",
            ClaimIn.model_validate(
                {
                    "kind": kind.value,
                    "provider_id": provider_id,
                }
            ),
        )
        return None if data is None else parse(ClaimOut, data)

    async def recover(self, provider_id: str) -> RecoveryOut | None:
        data = await self.api.post("/worker/sandbox/recover", ProviderIn(provider_id=provider_id))
        return None if data is None else parse(RecoveryOut, data)

    async def sandbox(
        self,
        task_id: UUID,
        operation: str,
        body: BaseModel,
        token: str | None = None,
    ) -> object:
        return await self.api.post(
            f"/worker/tasks/{task_id}/sandbox/{operation}", body, token=token
        )

    async def state(self, task_id: UUID, provider_id: str, token: str) -> SandboxState:
        return parse(
            SandboxState,
            await self.sandbox(
                task_id,
                "state",
                ProviderIn(provider_id=provider_id),
                token,
            ),
        )

    async def heartbeat(self, task_id: UUID, token: str) -> None:
        await self.api.post(f"/worker/tasks/{task_id}/heartbeat", token=token)

    async def report(
        self,
        task_id: UUID,
        endpoint: str,
        body: EventIn | CheckpointIn,
        token: str,
    ) -> TaskEventOut:
        return parse(
            TaskEventOut,
            await self.api.post(
                f"/worker/tasks/{task_id}/{endpoint}",
                body,
                token=token,
            ),
        )
