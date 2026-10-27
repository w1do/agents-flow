from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Input, Text

TaskStatus = Literal["new", "choosing", "planning", "backlog", "active", "testing", "ready",
                     "merged", "error", "stalled", "paused", "trash"]


class TaskCreate(Input):
    title: Text
    description: str
    source_type: Literal["web", "telegram_text", "telegram_voice", "api"]
    source_text: str


class TaskPatch(Input):
    status: Literal["new", "paused", "trash"]


class TaskEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    task_id: UUID
    agent_id: UUID | None
    event_id: str | None
    event_type: str
    message: str
    payload: dict[str, Any] | None
    created_at: datetime


class TaskSkillSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    task_id: UUID
    skill_id: UUID
    skill_name: str
    category: str
    skill_version: int
    content_hash: str
    content: str


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    title: str
    description: str
    source_type: str
    source_text: str
    status: TaskStatus
    assigned_agent_id: UUID | None
    lease_id: UUID | None
    lease_expires_at: datetime | None
    plan_text: str | None
    plan_revision: int
    plan_decision: str
    plan_feedback: str | None
    result_summary: str | None
    result_data: dict[str, Any] | None
    checkpoint: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    events: list[TaskEventResponse] = Field(default_factory=list)
    skill_snapshots: list[TaskSkillSnapshotResponse] = Field(default_factory=list)


class ExecutionStateResponse(BaseModel):
    task_id: UUID
    status: TaskStatus
    plan_decision: str
    plan_revision: int
    plan_feedback: str | None
    result_feedback: str | None
    publication_requested: bool
    lease_id: UUID
    lease_expires_at: datetime
    checkpoint: dict[str, Any] | None
