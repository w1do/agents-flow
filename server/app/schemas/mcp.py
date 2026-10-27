"""MCP arguments reuse REST report validation, including event_id checks."""
from typing import Any
from uuid import UUID

from app.schemas.reports import (
    EventRequest, FailRequest, PlanRequest, PublicationResultRequest, Report, ResultRequest,
)


class TaskCall(Report):
    task_id: UUID


class AssignedCall(Report):
    task_id: UUID | None = None


class PlanCall(TaskCall, PlanRequest):
    pass


class ProgressCall(TaskCall, EventRequest):
    pass


class CheckpointCall(TaskCall):
    checkpoint: dict[str, Any]
    message: str = "Checkpoint saved"
    payload: dict[str, Any] | None = None


class TestResultCall(TaskCall):
    message: str
    payload: dict[str, Any] | None = None


class ResultCall(TaskCall, ResultRequest):
    pass


class PublicationCall(TaskCall, PublicationResultRequest):
    pass


class FailureCall(TaskCall, FailRequest):
    pass


TOOL_SCHEMAS = {
    "agent_get_assigned_task": AssignedCall,
    "agent_heartbeat": TaskCall,
    "agent_report_plan": PlanCall,
    "agent_get_plan_decision": TaskCall,
    "agent_report_progress": ProgressCall,
    "agent_save_checkpoint": CheckpointCall,
    "agent_report_test_result": TestResultCall,
    "agent_report_result": ResultCall,
    "agent_get_result_decision": TaskCall,
    "agent_report_publication_result": PublicationCall,
    "agent_report_failure": FailureCall,
}
