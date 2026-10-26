"""Восстановление из серверной записи без доверия файлам песочницы (D-41)."""

from harness_shared.sandboxes import SandboxStatus
from harness_shared.worker_sandbox import RecoveryOut
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import Sandbox, Task
from harness_server.services.worker_queue import issue_claim
from harness_server.services.worker_sandbox import state
from harness_server.settings import Settings


async def recover(
    session: AsyncSession, provider_id: str, settings: Settings
) -> RecoveryOut | None:
    """Блокировки в порядке задача → песочница; во время очистки токен не перевыдаётся."""
    task_id = await session.scalar(
        select(Sandbox.current_task_id).where(
            Sandbox.provider_id == provider_id, Sandbox.status == SandboxStatus.ACTIVE
        )
    )
    if task_id is None:
        return None
    task = await session.scalar(select(Task).where(Task.id == task_id).with_for_update())
    row = await session.scalar(
        select(Sandbox)
        .where(Sandbox.provider_id == provider_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        task is None
        or row is None
        or row.current_task_id != task_id
        or row.status != SandboxStatus.ACTIVE
    ):
        return None
    snapshot = state(row)
    claim = await issue_claim(session, task, settings, cleanup=row.cleanup_started)
    return RecoveryOut(claim=claim, sandbox=snapshot)
