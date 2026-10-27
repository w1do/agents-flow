from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, StringConstraints, field_validator, model_validator

from app.schemas.common import Input, Text
from app.schemas.tasks import TaskStatus
from app.services.skill_content import contains_secret


class Report(Input):
    lease_id: UUID
    event_id: Annotated[str, StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128,
        pattern=r"^[A-Za-z0-9._:-]{1,128}$",
    )]

    @field_validator("event_id")
    @classmethod
    def reject_secret_ids(cls, value):
        if contains_secret(value):
            raise ValueError("event_id must not contain a secret")
        return value


class PlanRequest(Report):
    plan_text: Text


class EventRequest(Report):
    event_type: Annotated[str, StringConstraints(
        max_length=64, pattern=r"^[a-z][a-z0-9-]{0,63}$",
    )]
    message: str
    payload: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_status_type(self):
        status = (self.payload or {}).get("status")
        if status is not None and not isinstance(status, str):
            raise ValueError("payload.status must be a string")
        return self


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
