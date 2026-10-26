"""Серверный учёт песочницы. Команды процесса и файлов выполняет машина worker."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from harness_shared.sandboxes import SandboxStatus
from harness_shared.worker_sandbox import SandboxState, StartIn, StartOut
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import Sandbox, Task, TaskToken
from harness_server.domain.errors import WorkerConflict
from harness_server.services.worker_access import authorize_task


def state(row: Sandbox) -> SandboxState:
    """Снимок записи; ORM-объект не покидает сервис."""
    assert row.current_task_id is not None
    return SandboxState(
        provider_id=row.provider_id,
        task_id=row.current_task_id,
        started_at=row.agent_started_at,
        pid=row.agent_pid,
        launch_key=row.agent_launch_key,
        cleanup_started=row.cleanup_started,
    )


async def pinned(
    session: AsyncSession,
    task_id: UUID,
    provider_id: str,
    *,
    token: str | None,
    secret_key: str,
    cleanup: bool = False,
    released: bool = False,
) -> Sandbox:
    """Единый порядок блокировок: задача, затем песочница; cleanup переживает отзыв токена."""
    if not cleanup:
        await authorize_task(session, task_id, token or "", secret_key)
    else:
        await session.scalar(select(Task).where(Task.id == task_id).with_for_update())
    row = await session.scalar(
        select(Sandbox)
        .where(Sandbox.provider_id == provider_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise WorkerConflict()
    if released and row.current_task_id is None and row.last_released_task_id == task_id:
        return row
    if row.current_task_id != task_id:
        raise WorkerConflict()
    if cleanup and not row.cleanup_started:
        await authorize_task(session, task_id, token or "", secret_key)
    return row


async def reserve(
    session: AsyncSession, task_id: UUID, provider_id: str, token: str, secret_key: str
) -> SandboxState:
    """Закрепляет захваченную задачу либо возвращает уже существующее закрепление."""
    await authorize_task(session, task_id, token, secret_key)
    row = await session.scalar(
        select(Sandbox)
        .where(Sandbox.provider_id == provider_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.status == SandboxStatus.ERROR:
        raise WorkerConflict()
    if row.current_task_id not in (None, task_id):
        raise WorkerConflict()
    if row.current_task_id is None:
        row.current_task_id = task_id
        row.status = SandboxStatus.ACTIVE
        row.agent_started_at = None
        row.agent_pid = None
        row.agent_launch_key = None
        row.cleanup_started = False
    result = state(row)
    await session.commit()
    return result


async def record_start(session: AsyncSession, row: Sandbox, body: StartIn) -> StartOut:
    """Сохраняет отсчёт до exec; иной ключ не разрешает повторный запуск."""
    if row.cleanup_started or row.status != SandboxStatus.ACTIVE:
        raise WorkerConflict()
    key = sha256(body.external_key.encode()).hexdigest()
    if row.agent_started_at is None:
        row.agent_started_at = body.started_at
        row.agent_launch_key = key
    result = StartOut(state=state(row), launch=row.agent_launch_key == key)
    await session.commit()
    return result


async def record_pid(session: AsyncSession, row: Sandbox, pid: int) -> SandboxState:
    """Pid фиксируется один раз; конфликт не перезаписывает сведения о живом процессе."""
    if row.agent_started_at is None or row.agent_pid not in (None, pid):
        raise WorkerConflict()
    row.agent_pid = pid
    result = state(row)
    await session.commit()
    return result


async def begin_cleanup(session: AsyncSession, row: Sandbox) -> SandboxState:
    """Отзывает все токены до локальных команд; закрепление остаётся для восстановления."""
    await session.execute(
        update(TaskToken)
        .where(TaskToken.task_id == row.current_task_id, TaskToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    row.cleanup_started = True
    result = state(row)
    await session.commit()
    return result


async def finish_cleanup(session: AsyncSession, row: Sandbox, success: bool) -> None:
    """Успех означает, что worker завершил очистку и паузу; ошибка сохраняет доказательства."""
    if row.current_task_id is None and success:
        return
    if success and not row.cleanup_started:
        raise WorkerConflict()
    if success:
        row.last_released_task_id = row.current_task_id
        row.current_task_id = None
        row.agent_started_at = None
        row.agent_pid = None
        row.agent_launch_key = None
        row.cleanup_started = False
        row.status = SandboxStatus.PAUSED
    else:
        row.status = SandboxStatus.ERROR
    await session.commit()
