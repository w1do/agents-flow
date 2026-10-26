"""Авторизация записи worker: блокировка задачи и проверка срока, роли и отзыва токена."""

from datetime import UTC, datetime
from uuid import UUID

from harness_shared.sandboxes import AgentRole
from harness_shared.tasks import TaskKind
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import Task, TaskToken
from harness_server.domain.errors import WorkerUnauthorized
from harness_server.security.tokens import hash_token


async def authorize_task(session: AsyncSession, task_id: UUID, token: str, secret_key: str) -> Task:
    """Проверяет токен после блокировки задачи: отзыв и запись не гоняются между собой."""
    task = await session.scalar(
        select(Task)
        .where(Task.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    role = (
        AgentRole.PLANNER
        if task is not None and task.kind == TaskKind.PLAN
        else AgentRole.IMPLEMENTER
    )
    authorized = await session.scalar(
        select(TaskToken.id).where(
            TaskToken.task_id == task_id,
            TaskToken.token_hash == hash_token(token, secret_key),
            TaskToken.role == role,
            TaskToken.revoked_at.is_(None),
            TaskToken.expires_at > datetime.now(UTC),
        )
    )
    if task is None or authorized is None:
        raise WorkerUnauthorized()
    return task
