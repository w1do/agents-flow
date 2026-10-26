"""Контракты MCP планировщика и HTTP-проверок плана."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from harness_shared.tasks import TaskOut, TaskStatus, TaskText
from harness_shared.worker_reports import EventIn

ChangeId = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=128)
]
SpecKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*#[1-9][0-9]*$", max_length=64)]
AgentReportStatus = Literal["started", "progress", "completed", "failed"]


class SpecItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: SpecKey
    text: TaskText
    status: Annotated[str, StringConstraints(min_length=1, max_length=32)]


class SpecSyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_id: ChangeId
    items: list[SpecItemIn] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def matching_keys(self) -> "SpecSyncIn":
        if len({item.key for item in self.items}) != len(self.items):
            raise ValueError("duplicate_keys")
        if any(item.key.split("#")[0] != self.change_id for item in self.items):
            raise ValueError("change_key_mismatch")
        return self


class SpecItemOut(SpecItemIn):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: UUID
    change_id: str
    plan_task_id: UUID | None


class AgentTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: TaskText
    spec_item_key: SpecKey
    priority: int = Field(default=0, ge=-2147483648, le=2147483647)


class AgentReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: AgentReportStatus
    text: TaskText


class AgentListIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TaskStatus | None = None


class PlanState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    children: list[TaskOut]
    items: list[SpecItemOut]
    report_status: Literal["completed", "failed"] | None = None


class PlanFinishIn(EventIn):
    status: Literal["ready", "error"]
    branch: str | None = Field(default=None, max_length=255)
