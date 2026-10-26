"""HTTP-реализация порта учёта запуска и очистки локального агента."""

from datetime import datetime
from uuid import UUID, uuid4

from harness_shared.worker import ClaimOut
from harness_shared.worker_sandbox import (
    AgentRunInfo,
    CleanupIn,
    PidIn,
    ProviderIn,
    StartIn,
    StartOut,
)
from pydantic import SecretStr

from harness_server.worker.client import WorkerClient, parse


class RemoteAgentStore:
    """Ключ запуска создаётся один раз на попытку; сетевые повторы используют то же тело."""

    def __init__(self, client: WorkerClient, claim: ClaimOut, provider_id: str) -> None:
        self.client = client
        self.claim = claim
        self.provider_id = provider_id
        self.launch_key = str(uuid4())

    async def info(self) -> AgentRunInfo:
        return await self.client.state(self.claim.task.id, self.provider_id, self.claim.task_token)

    async def record_pid(self, pid: int) -> None:
        await self.client.sandbox(
            self.claim.task.id,
            "pid",
            PidIn(provider_id=self.provider_id, pid=pid),
            self.claim.task_token,
        )

    async def record_started(self, started_at: datetime) -> bool:
        data = await self.client.sandbox(
            self.claim.task.id,
            "start",
            StartIn(
                provider_id=self.provider_id,
                external_key=self.launch_key,
                started_at=started_at,
            ),
            self.claim.task_token,
        )
        return parse(StartOut, data).launch

    async def issue_token(
        self, task_id: UUID, secret_key: SecretStr | None, timeout_min: int, now: datetime
    ) -> str:
        return self.claim.task_token

    async def revoke_tokens(self, task_id: UUID) -> None:
        await self.client.sandbox(
            task_id, "cleanup", ProviderIn(provider_id=self.provider_id), self.claim.task_token
        )

    async def mark_error(self) -> None:
        await self.client.sandbox(
            self.claim.task.id,
            "release",
            CleanupIn(provider_id=self.provider_id, success=False),
            self.claim.task_token,
        )

    async def release(self) -> None:
        await self.client.sandbox(
            self.claim.task.id,
            "release",
            CleanupIn(provider_id=self.provider_id, success=True),
            self.claim.task_token,
        )
