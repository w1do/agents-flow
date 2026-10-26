"""Отклонение дочерних задач в транзакции изменения статуса плана."""

from harness_shared.tasks import TaskEventSource, TaskKind, TaskStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import Task, TaskEvent
from harness_server.domain.errors import WorkerConflict
from harness_server.domain.statuses import ensure_transition


async def discard_children(session: AsyncSession, plan: Task, text: str) -> None:
    """Без commit: откат любого шага отменяет также error родителя."""
    rows = await session.scalars(
        select(Task)
        .where(
            Task.parent_id == plan.id,
            Task.kind == TaskKind.IMPLEMENT,
        )
        .order_by(Task.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    for child in rows:
        if child.status == TaskStatus.TRASH:
            continue
        if child.status != TaskStatus.BACKLOG:
            raise WorkerConflict()
        ensure_transition(child.kind, child.status, TaskStatus.TRASH)
        child.status = TaskStatus.TRASH
        session.add(
            TaskEvent(
                task_id=child.id,
                status=TaskStatus.TRASH,
                source=TaskEventSource.WORKER,
                text=text,
            )
        )
