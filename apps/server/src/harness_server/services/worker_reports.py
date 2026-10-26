"""Атомарные идемпотентные отчёты worker и обязательная редакция перед записью."""

from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

from harness_shared.tasks import TaskEventOut, TaskEventSource
from harness_shared.worker_reports import CheckpointIn, EventIn, ResultIn, StatusIn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import Checkpoint, TaskEvent
from harness_server.domain.statuses import ensure_transition
from harness_server.security.redaction import redact
from harness_server.services.worker_access import authorize_task


async def report(
    session: AsyncSession,
    task_id: UUID,
    body: EventIn | CheckpointIn,
    *,
    token: str,
    secret_key: str,
    secrets: Sequence[str],
) -> TaskEventOut:
    """Ключ общий для всех видов отчёта; повтор возвращает тот же снимок события."""
    task = await authorize_task(session, task_id, token, secret_key)
    key = sha256(body.external_key.encode()).hexdigest()
    existing = await session.scalar(
        select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.external_key == key)
    )
    if existing is not None:
        return TaskEventOut.model_validate(existing)
    safe = type(body).model_validate_json(
        redact(body.model_dump_json(), extra_values=(*secrets, token))
    )
    if isinstance(safe, StatusIn):
        ensure_transition(task.kind, task.status, safe.status)
        task.status = safe.status
    if isinstance(safe, CheckpointIn):
        session.add(Checkpoint(task_id=task_id, **safe.model_dump(exclude={"external_key"})))
        text = safe.summary
    else:
        text = safe.text
    if isinstance(safe, ResultIn):
        task.result = safe.text
        task.branch = safe.branch
        task.mr_url = safe.mr_url
        task.tests_state = safe.tests_state
    event = TaskEvent(
        task_id=task_id,
        status=task.status,
        text=text,
        source=TaskEventSource.WORKER,
        external_key=key,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return TaskEventOut.model_validate(event)
