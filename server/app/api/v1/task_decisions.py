from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import Database
from app.api.flow_deps import Write, flow_admin
from app.schemas.reports import PlanDecisionRequest, ResultDecisionRequest
from app.schemas.tasks import TaskResponse
from app.services import decisions

router = APIRouter(prefix="/tasks", tags=["decisions"], dependencies=[Depends(flow_admin)])


@router.post("/{task_id}/plan/decision", response_model=TaskResponse)
def plan(task_id: UUID, body: PlanDecisionRequest, session: Database, write: Write):
    return write.run(body, lambda: decisions.decide(session, task_id, "plan", body))


@router.post("/{task_id}/result/decision", response_model=TaskResponse)
def result(task_id: UUID, body: ResultDecisionRequest, session: Database, write: Write):
    return write.run(body, lambda: decisions.decide(session, task_id, "result", body))
