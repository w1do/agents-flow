"""Translate MCP arguments into the existing execution services."""
from fastapi import HTTPException

from app.repositories.task import TaskRepository
from app.schemas.leases import HeartbeatRequest
from app.schemas.reports import (
    EventRequest, FailRequest, PlanRequest, PublicationResultRequest, ResultRequest,
)
from app.services import leases, reports, tasks

REPORTS = {
    "agent_report_plan": ("plan", PlanRequest),
    "agent_report_progress": ("events", EventRequest),
    "agent_report_result": ("result", ResultRequest),
    "agent_report_publication_result": ("publication-result", PublicationResultRequest),
    "agent_report_failure": ("fail", FailRequest),
}


def execute(session, agent, name, body):
    task_id = body.task_id
    if name == "agent_get_assigned_task":
        if task_id is None:
            assigned = TaskRepository(session).leased(agent.id)
            if not assigned:
                raise HTTPException(409, "Invalid lease")
            task_id = assigned[0].id
        task = leases.agent_task(session, task_id, agent, body.lease_id)
        state = reports.execution_state(session, task_id, agent, body.lease_id)
        return {"task": tasks.card(session, task), "execution_state": state}
    if name in {"agent_get_plan_decision", "agent_get_result_decision"}:
        return reports.execution_state(session, task_id, agent, body.lease_id)
    if name == "agent_heartbeat":
        return leases.heartbeat(session, agent, HeartbeatRequest(
            task_id=task_id, lease_id=body.lease_id,
        ))
    values = body.model_dump(exclude={"task_id"})
    if name in {"agent_save_checkpoint", "agent_report_test_result"}:
        if values.get("payload") is not None:
            values["payload"].pop("status", None)
        values["event_type"] = ("checkpoint" if name == "agent_save_checkpoint" else "test_result")
        kind, schema = "events", EventRequest
    else:
        kind, schema = REPORTS[name]
    return reports.report(session, task_id, agent, kind, schema.model_validate(values))
