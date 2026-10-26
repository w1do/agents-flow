"""Состояние и идемпотентное завершение плана на сервере."""

from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

from harness_shared.planning import PlanFinishIn, PlanState, SpecItemOut
from harness_shared.tasks import TaskEventOut, TaskKind, TaskOut, TaskStatus
from harness_shared.worker_reports import StatusIn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import SpecItem, Task, TaskEvent
from harness_server.domain.errors import WorkerConflict
from harness_server.security.redaction import redact
from harness_server.services.agent_access import terminal_report
from harness_server.services.worker_access import authorize_task
from harness_server.services.worker_reports import report


async def read_state(session: AsyncSession, plan: Task, secrets: Sequence[str]) -> PlanState:
    """Только свои дети и пункты, без значений секретов в ответе."""
    if plan.kind != TaskKind.PLAN:
        raise WorkerConflict()
    children = await session.scalars(
        select(Task)
        .where(
            Task.parent_id == plan.id,
            Task.kind == TaskKind.IMPLEMENT,
        )
        .order_by(Task.created_at, Task.id)
    )
    items = await session.scalars(
        select(SpecItem)
        .where(
            SpecItem.plan_task_id == plan.id,
            SpecItem.workspace_id == plan.workspace_id,
        )
        .order_by(SpecItem.key)
    )
    status = await terminal_report(session, plan.id)
    state = PlanState(
        children=[TaskOut.model_validate(child) for child in children],
        items=[SpecItemOut.model_validate(item) for item in items],
        report_status="completed" if status == "completed" else "failed" if status else None,
    )
    return PlanState.model_validate_json(redact(state.model_dump_json(), secrets))


async def finish(
    session: AsyncSession,
    task_id: UUID,
    body: PlanFinishIn,
    *,
    token: str,
    secret_key: str,
    secrets: Sequence[str],
) -> TaskEventOut:
    """Готовность подтверждает worker; ошибка отбрасывает детей внутри report."""
    plan = await authorize_task(session, task_id, token, secret_key)
    if plan.kind != TaskKind.PLAN:
        raise WorkerConflict()
    key = sha256(body.external_key.encode()).hexdigest()
    existing = await session.scalar(
        select(TaskEvent).where(
            TaskEvent.task_id == task_id,
            TaskEvent.external_key == key,
        )
    )
    if existing is not None:
        event = TaskEventOut.model_validate(existing)
        # Уведомление берёт блокировку плана в другой сессии после возврата из finish.
        await session.commit()
        return event
    if body.status == "ready":
        state = await read_state(session, plan, (*secrets, token))
        item_ids = {item.id for item in state.items}
        if (
            body.branch != f"task/{plan.id}"
            or state.report_status != "completed"
            or not state.children
            or any(
                child.status != TaskStatus.BACKLOG
                or child.spec_item_id not in item_ids
                or child.workspace_id != plan.workspace_id
                for child in state.children
            )
        ):
            raise WorkerConflict()
        plan.branch = body.branch
        plan.result = redact(body.text, (*secrets, token))
    return await report(
        session,
        task_id,
        StatusIn(external_key=body.external_key, status=TaskStatus(body.status), text=body.text),
        token=token,
        secret_key=secret_key,
        secrets=secrets,
    )
