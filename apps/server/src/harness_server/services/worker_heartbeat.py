"""Heartbeat задач и серверный контроль зависания с короткими транзакциями."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from harness_shared.tasks import TaskEventSource, TaskStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harness_server.db.models import Task, TaskEvent
from harness_server.domain.statuses import ensure_transition
from harness_server.services.worker_access import authorize_task

logger = logging.getLogger(__name__)
RUNNING_STATUSES = (TaskStatus.PLANNING, TaskStatus.ACTIVE, TaskStatus.TESTING)


async def heartbeat(session: AsyncSession, task_id: UUID, token: str, secret_key: str) -> None:
    """Обновляет время только по действующему токену этой задачи."""
    task = await authorize_task(session, task_id, token, secret_key)
    task.worker_heartbeat_at = datetime.now(UTC)
    await session.commit()


async def expire_heartbeats(
    session: AsyncSession, timeout_sec: float, *, now: datetime | None = None
) -> int:
    """Атомарно ставит stalled и событие; повтор и конкурирующий монитор безопасны."""
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=timeout_sec)
    tasks = (
        await session.scalars(
            select(Task)
            .where(Task.worker_heartbeat_at < cutoff, Task.status.in_(RUNNING_STATUSES))
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    for task in tasks:
        ensure_transition(task.kind, task.status, TaskStatus.STALLED)
        task.status = TaskStatus.STALLED
        session.add(
            TaskEvent(
                task_id=task.id,
                status=TaskStatus.STALLED,
                text="worker heartbeat expired",
                source=TaskEventSource.API,
            )
        )
    await session.commit()
    return len(tasks)


async def monitor(factory: async_sessionmaker[AsyncSession], timeout_sec: float) -> None:
    """Серверный фон; отмена в lifespan закрывает сессию до остановки engine."""
    while True:
        await asyncio.sleep(min(15.0, timeout_sec / 2))
        try:
            async with factory() as session:
                await expire_heartbeats(session, timeout_sec)
        except Exception as exc:
            logger.warning("heartbeat monitor failed type=%s", type(exc).__name__)
