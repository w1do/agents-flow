"""Атомарная выдача очереди worker вместе с ограниченным токеном задачи."""

from datetime import UTC, datetime, timedelta

from harness_shared.projects import Workspace
from harness_shared.sandboxes import AgentRole, SandboxStatus
from harness_shared.tasks import TaskKind, TaskOut, TaskStatus
from harness_shared.worker import ClaimIn, ClaimOut
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.config import HarnessConfig
from harness_server.db.models import Sandbox, Task, TaskToken
from harness_server.domain.errors import WorkerConflict
from harness_server.security.redaction import redact
from harness_server.services.projects import get_workspace
from harness_server.services.sandboxes import TOKEN_EXPIRY_MARGIN, ensure_sandbox, issue_task_token
from harness_server.services.tasks import lock_next_task
from harness_server.settings import Settings
from harness_server.wiring import secret_values


async def claim(
    session: AsyncSession, body: ClaimIn, settings: Settings, config: HarnessConfig | None = None
) -> ClaimOut | None:
    """Захват, событие и выдача токена коммитятся одной транзакцией в issue_task_token."""
    sandbox = None
    if body.provider_id is not None:
        if config is None or body.provider_id != config.sandbox.provider_id:
            raise WorkerConflict()
        await ensure_sandbox(session, config)
        sandbox = await session.scalar(
            select(Sandbox)
            .where(
                Sandbox.provider_id == body.provider_id,
                Sandbox.current_task_id.is_(None),
                Sandbox.status == SandboxStatus.PAUSED,
            )
            .with_for_update(skip_locked=True)
        )
        if sandbox is None:
            await session.rollback()
            return None
    kind = TaskKind(body.kind)
    planning = kind == TaskKind.PLAN
    task = await lock_next_task(
        session,
        kind=kind,
        from_status=TaskStatus.PLANNING if planning else TaskStatus.BACKLOG,
        to_status=None if planning else TaskStatus.ACTIVE,
        worker_api=True,
    )
    if task is None:
        await session.rollback()
        return None
    # READ COMMITTED: второй запрос после блокировки видит токен, закоммиченный другим
    # worker после snapshot первого SELECT. У plan сам статус при захвате не меняется.
    claimed = await session.scalar(
        select(TaskToken.id)
        .where(TaskToken.task_id == task.id, TaskToken.revoked_at.is_(None))
        .limit(1)
    )
    if claimed is not None:
        await session.rollback()
        return None
    if sandbox is not None:
        sandbox.current_task_id = task.id
        sandbox.status = SandboxStatus.ACTIVE
        sandbox.agent_started_at = None
        sandbox.agent_pid = None
        sandbox.agent_launch_key = None
        sandbox.cleanup_started = False
    return await issue_claim(session, task, settings)


async def issue_claim(
    session: AsyncSession, task: Task, settings: Settings, *, cleanup: bool = False
) -> ClaimOut:
    """Снимок и новый токен; существующий токен агента жив до очистки (D-41)."""
    planning = task.kind == TaskKind.PLAN
    assert task.workspace_id is not None
    project = await get_workspace(session, task.workspace_id)
    now = datetime.now(UTC)
    task.worker_heartbeat_at = now
    token = (
        ""
        if cleanup
        else await issue_task_token(
            session,
            task.id,
            secret_key=settings.harness_secret_key.get_secret_value(),
            agent_run_timeout_min=settings.agent_run_timeout_min,
            now=now,
        )
    )
    if cleanup:
        await session.commit()
    await session.refresh(task)
    # Поля пользователя также могут содержать секреты; сам выданный токен не редактируется.
    task_out = TaskOut.model_validate_json(
        redact(TaskOut.model_validate(task).model_dump_json(), extra_values=secret_values(settings))
    )
    project = Workspace.model_validate_json(
        redact(project.model_dump_json(), extra_values=secret_values(settings))
    )
    return ClaimOut(
        task=task_out,
        project=project,
        task_token=token,
        role=AgentRole.PLANNER if planning else AgentRole.IMPLEMENTER,
        expires_at=now + timedelta(minutes=settings.agent_run_timeout_min) + TOKEN_EXPIRY_MARGIN,
    )
