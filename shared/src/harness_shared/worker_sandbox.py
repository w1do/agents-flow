"""HTTP-контракты серверного учёта локальной песочницы (D-41)."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from harness_shared.worker import ClaimOut
from harness_shared.worker_reports import EventKey


class ProviderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1, max_length=128)


class AgentRunInfo(BaseModel):
    started_at: AwareDatetime | None = None
    pid: int | None = Field(default=None, ge=2, le=2**22, strict=True)


class SandboxState(AgentRunInfo):
    provider_id: str
    task_id: UUID
    launch_key: str | None = None
    cleanup_started: bool = False


class RecoveryOut(BaseModel):
    claim: ClaimOut
    sandbox: SandboxState


class StartIn(ProviderIn):
    external_key: EventKey
    started_at: AwareDatetime


class StartOut(BaseModel):
    state: SandboxState
    launch: bool


class PidIn(ProviderIn):
    pid: int = Field(ge=2, le=2**22, strict=True)


class CleanupIn(ProviderIn):
    success: bool
