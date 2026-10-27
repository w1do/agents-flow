from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.schemas.common import Input
from app.schemas.harness import SkillFile
from app.schemas.tasks import TaskResponse


class ClaimRequest(Input):
    pass


class ClaimResponse(BaseModel):
    task: TaskResponse
    skills: list[SkillFile]
    lease_id: UUID
    lease_expires_at: datetime


class HeartbeatRequest(Input):
    task_id: UUID | None
    lease_id: UUID | None

    @model_validator(mode="after")
    def paired_lease(self):
        if (self.task_id is None) != (self.lease_id is None):
            raise ValueError("task_id и lease_id передаются вместе")
        return self


class HeartbeatResponse(BaseModel):
    status: Literal["online", "busy"]
    lease_expires_at: datetime | None
