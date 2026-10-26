"""Правила инструментов агента; транспорт MCP только разбирает DTO."""

from collections.abc import Sequence
from hashlib import sha256

from harness_shared.planning import AgentListIn, AgentReportIn, AgentTaskIn, SpecSyncIn
from harness_shared.tasks import TaskEventOut, TaskEventSource, TaskKind, TaskOut, TaskSource
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import SpecItem, Task, TaskEvent
from harness_server.domain.errors import Forbidden
from harness_server.security.redaction import redact
from harness_server.services import tasks
from harness_server.services.agent_access import agent_task, require_planner, terminal_report
from harness_server.services.spec import sync_items


async def create_implementation(
    session: AsyncSession, plan: Task, body: AgentTaskIn, secrets: Sequence[str]
) -> TaskOut:
    """Повтор по своему пункту возвращает прежнюю задачу."""
    item = await session.scalar(
        select(SpecItem).where(
            SpecItem.workspace_id == plan.workspace_id,
            SpecItem.plan_task_id == plan.id,
            SpecItem.key == body.spec_item_key,
        )
    )
    if item is None:
        raise Forbidden("foreign_spec_item")
    existing = await session.scalar(
        select(Task).where(
            Task.parent_id == plan.id,
            Task.spec_item_id == item.id,
            Task.kind == TaskKind.IMPLEMENT,
        )
    )
    if existing is not None:
        return TaskOut.model_validate(existing)
    assert plan.workspace_id is not None
    task = await tasks.create_task(
        session,
        kind=TaskKind.IMPLEMENT,
        text=redact(body.text, secrets),
        source=TaskSource.SPEC,
        known_workspace_ids=[plan.workspace_id],
        workspace_id=plan.workspace_id,
        parent_id=plan.id,
        spec_item_id=item.id,
        priority=body.priority,
    )
    return TaskOut.model_validate(task)


async def report_agent(
    session: AsyncSession, task: Task, body: AgentReportIn, secrets: Sequence[str]
) -> TaskEventOut:
    """Финальный сигнал идемпотентен и не присваивает ready."""
    text = redact(body.text, secrets)
    suffix = (
        "" if body.status in ("completed", "failed") else ":" + sha256(text.encode()).hexdigest()
    )
    key = f"agent-report:{body.status}{suffix}"
    existing = await session.scalar(
        select(TaskEvent).where(
            TaskEvent.task_id == task.id,
            TaskEvent.external_key == key,
        )
    )
    if existing is not None:
        return TaskEventOut.model_validate(existing)
    if task.status not in ("planning", "active", "testing") or (
        await terminal_report(session, task.id) is not None
    ):
        raise Forbidden("agent_finished")
    event = TaskEvent(
        task_id=task.id,
        status=task.status,
        text=text,
        source=TaskEventSource.AGENT,
        external_key=key,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return TaskEventOut.model_validate(event)


async def invoke(
    session: AsyncSession,
    token: str,
    secret_key: str,
    name: str,
    body: BaseModel,
    secrets: Sequence[str],
) -> object:
    """Проверяет доступ непосредственно перед инструментом, даже в существующей MCP-сессии."""
    task = await agent_task(session, token, secret_key)
    values = (*secrets, token)
    if isinstance(body, AgentReportIn) and name == "report_task":
        return await report_agent(session, task, body, values)
    if isinstance(body, AgentListIn) and name == "list_tasks":
        rows = await tasks.list_tasks(
            session,
            workspace_id=task.workspace_id,
            statuses=None if body.status is None else [body.status],
        )
        return [TaskOut.model_validate(row) for row in rows]
    await require_planner(session, task)
    if isinstance(body, SpecSyncIn) and name == "sync_spec":
        return await sync_items(session, task, body, values)
    if isinstance(body, AgentTaskIn) and name == "create_task":
        return await create_implementation(session, task, body, values)
    raise Forbidden("unknown_tool")
