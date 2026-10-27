from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.schemas.common import Input, Text
from app.schemas.tasks import TaskStatus


class Report(Input):
    lease_id: UUID
    event_id: Text


class PlanRequest(Report):
    plan_text: Text


class EventRequest(Report):
    event_type: Text
    message: str
    payload: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None


class ResultRequest(Report):
    result_summary: str
    result_data: dict[str, Any]


class PublicationResultRequest(Report):
    success: bool
    message: str
    payload: dict[str, Any] | None = None


class FailRequest(Report):
    message: str
    payload: dict[str, Any] | None = None


class ReportResponse(BaseModel):
    task_id: UUID
    status: TaskStatus
    event_id: str


class Decision(Input):
    feedback: str | None = None

    @model_validator(mode="after")
    def require_feedback(self):
        if self.decision in {"rejected", "rework"} and not (self.feedback or "").strip():
            raise ValueError("Нужен непустой feedback")
        return self


class PlanDecisionRequest(Decision):
    decision: Literal["approved", "rejected", "trash"]


class ResultDecisionRequest(Decision):
    decision: Literal["publish", "rework", "keep_ready"]
