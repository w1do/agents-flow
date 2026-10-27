from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Database
from app.api.flow_deps import AgentActor, Write
from app.schemas.reports import (
    EventRequest, FailRequest, PlanRequest, PublicationResultRequest, ReportResponse, ResultRequest,
)
from app.schemas.tasks import ExecutionStateResponse
from app.services import reports

router = APIRouter(prefix="/tasks", tags=["reports"])


@router.get("/{task_id}/execution-state", response_model=ExecutionStateResponse)
def state(task_id: UUID, lease_id: UUID, actor: AgentActor, session: Database):
    return reports.execution_state(session, task_id, actor, lease_id)


@router.post("/{task_id}/plan", response_model=ReportResponse)
def plan(task_id: UUID, body: PlanRequest, actor: AgentActor, session: Database, write: Write):
    return write.run(body, lambda: reports.report(session, task_id, actor, "plan", body))


@router.post("/{task_id}/events", response_model=ReportResponse)
def events(task_id: UUID, body: EventRequest, actor: AgentActor, session: Database, write: Write):
    return write.run(body, lambda: reports.report(session, task_id, actor, "events", body))


@router.post("/{task_id}/result", response_model=ReportResponse)
def result(task_id: UUID, body: ResultRequest, actor: AgentActor, session: Database, write: Write):
    return write.run(body, lambda: reports.report(session, task_id, actor, "result", body))


@router.post("/{task_id}/publication-result", response_model=ReportResponse)
def publication(task_id: UUID, body: PublicationResultRequest, actor: AgentActor,
                session: Database, write: Write):
    return write.run(body, lambda: reports.report(session, task_id, actor, "publication-result", body))


@router.post("/{task_id}/fail", response_model=ReportResponse)
def fail(task_id: UUID, body: FailRequest, actor: AgentActor, session: Database, write: Write):
    return write.run(body, lambda: reports.report(session, task_id, actor, "fail", body))
