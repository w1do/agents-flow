"""Observe the existing service event journal without changing REST/MCP contracts."""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import Project, Task, TaskEvent
from app.services.telegram_delivery import ChatQueueFull, Scheduler
from app.services.notifications import build

logger = logging.getLogger(__name__)


@asynccontextmanager
async def running(runtime, engine):
    scheduler = Scheduler(runtime)
    loop, queue, key = asyncio.get_running_loop(), scheduler.queue, object()
    runtime.notifications = queue

    def capture(session, _context):
        if session.get_bind() is not engine:
            return
        try:
            for row in list(session.new):
                if not isinstance(row, TaskEvent):
                    continue
                task = next((item for item in session.new
                             if isinstance(item, Task) and item.id == row.task_id), None)
                task = task if task is not None else session.get(Task, row.task_id)
                project = session.get(Project, task.project_id)
                notice = build(task, project, row, runtime.settings)
                if notice:
                    session.info.setdefault(key, []).append(notice)
        except Exception:
            logger.warning("telegram_notification_capture_failed")

    def enqueue(notices):
        for notice in notices:
            try:
                queue.put_nowait(notice)
            except ChatQueueFull:
                logger.warning("telegram_notification_chat_quota_full")
            except asyncio.QueueFull:
                logger.warning("telegram_notification_queue_full")

    def commit(session):
        if not session.in_nested_transaction():
            notices = session.info.pop(key, [])
            if notices:
                loop.call_soon_threadsafe(enqueue, notices)

    def rollback(session):
        session.info.pop(key, None)

    hooks = (("after_flush", capture), ("after_commit", commit), ("after_rollback", rollback))
    for name, callback in hooks:
        event.listen(Session, name, callback)
    worker = asyncio.create_task(scheduler.run())
    try:
        yield
    finally:
        for name, callback in hooks:
            event.remove(Session, name, callback)
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        await scheduler.close()
