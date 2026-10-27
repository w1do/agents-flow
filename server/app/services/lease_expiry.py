import asyncio
import logging
from contextlib import suppress

from app.core import time
from app.repositories.agent import AgentRepository
from app.repositories.task import TaskRepository
from app.repositories.task_history import TaskHistory
from app.services.task_status import transition
from app.services.leases import release


def expire_due(session, project_id=None):
    expired = TaskRepository(session).expired(time.now(), project_id)
    for task in expired:
        agent = AgentRepository(session).lock(task.assigned_agent_id)
        if task.status != "merged":
            transition(task, "stalled")
        release(session, task, clear=True)
        if agent:
            agent.status = "offline"
        TaskHistory(session).append(task.id, "lease_expired", "Срок аренды истёк")
    if expired:
        session.commit()


async def monitor():
    while True:
        await asyncio.sleep(time.POLL_INTERVAL_SECONDS)
        try:
            await run_expiry_in_thread()
        except Exception:
            logging.getLogger(__name__).error("Не удалось проверить истечение аренды")


def _expire_once():
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        expire_due(session)


async def run_expiry_in_thread():
    await asyncio.to_thread(_expire_once)


async def stop_monitor(task):
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
