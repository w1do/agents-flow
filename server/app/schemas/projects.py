from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: str | None = None
    telegram_chat_id: str | None = None


class AgentSummary(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    status: str
    last_heartbeat_at: datetime | None
    git_remote: str
    repository_path_hint: str
    created_at: datetime
    updated_at: datetime


class ProjectSummary(BaseModel):
    id: UUID
    name: str
    description: str | None
    active_task_count: int
    agents: list[AgentSummary]
    telegram_chat_id: str | None
    created_at: datetime
    updated_at: datetime
    init_code_expires_at: datetime | None = None


class ProjectCard(ProjectSummary):
    pass


class InitTokenResponse(BaseModel):
    code: str = Field(repr=False)
    expires_at: datetime
