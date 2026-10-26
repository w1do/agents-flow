"""Авторизация MCP и ограничения записи планировщика."""

from uuid import UUID

from harness_shared.tasks import TaskKind, TaskStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import Task, TaskEvent, TaskToken
from harness_server.domain.errors import Forbidden, WorkerUnauthorized
from harness_server.security.tokens import hash_token
from harness_server.services.worker_access import authorize_task


async def agent_task(session: AsyncSession, token: str, secret_key: str) -> Task:
    """Находит задачу по хешу; после блокировки перепроверяет срок, роль и отзыв."""
    task_id = await session.scalar(
        select(TaskToken.task_id).where(TaskToken.token_hash == hash_token(token, secret_key))
    )
    if task_id is None:
        raise WorkerUnauthorized()
    task = await authorize_task(session, task_id, token, secret_key)
    if task.workspace_id is None:
        raise WorkerUnauthorized()
    return task


async def terminal_report(session: AsyncSession, task_id: UUID) -> str | None:
    """Последний финальный сигнал агента; completed сам по себе не меняет статус."""
    key = await session.scalar(
        select(TaskEvent.external_key)
        .where(
            TaskEvent.task_id == task_id,
            TaskEvent.source == "agent",
            TaskEvent.external_key.in_(["agent-report:completed", "agent-report:failed"]),
        )
        .order_by(TaskEvent.created_at.desc(), TaskEvent.id.desc())
        .limit(1)
    )
    return None if key is None else key.removeprefix("agent-report:")


async def require_planner(session: AsyncSession, task: Task) -> None:
    """Запрещает изменение зеркала и задач после финального отчёта."""
    if (
        task.kind != TaskKind.PLAN
        or task.status != TaskStatus.PLANNING
        or await terminal_report(session, task.id) is not None
    ):
        raise Forbidden("planner_required")
