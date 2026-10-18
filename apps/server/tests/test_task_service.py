"""Сервис задач на реальной Postgres в одной транзакции (db_session): сценарии task-lifecycle."""

import pytest
from harness_server.db.ids import uuid7
from harness_server.db.models import Task
from harness_server.domain.errors import (
    InvalidStatus,
    InvalidTransition,
    NotFound,
    UnknownWorkspace,
    UnsupportedKind,
)
from harness_server.services.tasks import (
    add_event,
    change_status,
    create_task,
    get_task,
    list_task_events,
    list_tasks,
)
from harness_shared.tasks import TaskEventSource, TaskKind, TaskSource, TaskStatus
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio(loop_scope="session")

KNOWN = ["ws-1"]


async def _plan(session: AsyncSession, workspace_id: str | None = None) -> Task:
    return await create_task(
        session,
        kind=TaskKind.PLAN,
        text="идея",
        source=TaskSource.API,
        known_workspace_ids=KNOWN,
        workspace_id=workspace_id,
    )


async def _implement(session: AsyncSession, workspace_id: str | None = "ws-1") -> Task:
    return await create_task(
        session,
        kind=TaskKind.IMPLEMENT,
        text="реализация",
        source=TaskSource.API,
        known_workspace_ids=KNOWN,
        workspace_id=workspace_id,
    )


async def test_create_plan_task_starts_new(db_session: AsyncSession) -> None:
    task = await _plan(db_session)

    assert task.kind == TaskKind.PLAN
    assert task.status == TaskStatus.NEW
    # Создание задачи событие не пишет (D-25).
    assert await list_task_events(db_session, task.id) == []


async def test_create_implement_task_starts_backlog(db_session: AsyncSession) -> None:
    task = await _implement(db_session)

    assert task.status == TaskStatus.BACKLOG
    assert await list_task_events(db_session, task.id) == []


async def test_create_check_task_unsupported(db_session: AsyncSession) -> None:
    with pytest.raises(UnsupportedKind):
        await create_task(
            db_session,
            kind=TaskKind.CHECK,
            text="проверка",
            source=TaskSource.API,
            known_workspace_ids=KNOWN,
        )


async def test_create_task_unknown_workspace(db_session: AsyncSession) -> None:
    with pytest.raises(UnknownWorkspace):
        await _plan(db_session, workspace_id="nope")


async def test_create_task_missing_parent_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFound):
        await create_task(
            db_session,
            kind=TaskKind.PLAN,
            text="дочерняя",
            source=TaskSource.API,
            known_workspace_ids=KNOWN,
            parent_id=uuid7(),
        )


async def test_allowed_transition_writes_event(db_session: AsyncSession) -> None:
    task = await _plan(db_session)

    await change_status(db_session, task.id, TaskStatus.CHOOSING, source=TaskEventSource.API)
    await change_status(
        db_session, task.id, TaskStatus.PLANNING, source=TaskEventSource.AGENT, text="план"
    )

    events = await list_task_events(db_session, task.id)
    assert events[-1].status == TaskStatus.PLANNING
    assert events[-1].source == TaskEventSource.AGENT
    assert events[-1].text == "план"


async def test_skipping_stage_rejected(db_session: AsyncSession) -> None:
    task = await _implement(db_session)

    with pytest.raises(InvalidTransition):
        await change_status(db_session, task.id, TaskStatus.READY, source=TaskEventSource.API)

    await db_session.refresh(task)
    assert task.status == TaskStatus.BACKLOG
    assert await list_task_events(db_session, task.id) == []


async def test_unknown_status_rejected(db_session: AsyncSession) -> None:
    task = await _plan(db_session)

    with pytest.raises(InvalidStatus):
        await change_status(db_session, task.id, "completed", source=TaskEventSource.API)

    await db_session.refresh(task)
    assert task.status == TaskStatus.NEW


async def test_database_rejects_unknown_status(db_session: AsyncSession) -> None:
    task = await _plan(db_session)

    # Прямой UPDATE в обход сервиса: отказ должен дать CHECK ck_tasks_status.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE tasks SET status = :status WHERE id = :id"),
                {"status": "completed", "id": task.id},
            )


async def test_event_history_in_order(db_session: AsyncSession) -> None:
    task = await _implement(db_session)
    for target in (TaskStatus.ACTIVE, TaskStatus.TESTING, TaskStatus.READY):
        await change_status(db_session, task.id, target, source=TaskEventSource.WORKER)

    events = await list_task_events(db_session, task.id)

    assert [event.status for event in events] == [
        TaskStatus.ACTIVE,
        TaskStatus.TESTING,
        TaskStatus.READY,
    ]


async def test_add_event_keeps_status(db_session: AsyncSession) -> None:
    task = await _plan(db_session)
    await change_status(db_session, task.id, TaskStatus.CHOOSING, source=TaskEventSource.API)

    event = await add_event(db_session, task.id, text="отчёт", source=TaskEventSource.AGENT)

    assert event.status == TaskStatus.CHOOSING
    await db_session.refresh(task)
    assert task.status == TaskStatus.CHOOSING


async def test_get_task_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFound):
        await get_task(db_session, uuid7())


async def test_list_tasks_filters_by_workspace_and_status(db_session: AsyncSession) -> None:
    plan_in_ws = await _plan(db_session, workspace_id="ws-1")
    await _plan(db_session)
    implement_in_ws = await _implement(db_session, workspace_id="ws-1")

    by_workspace = await list_tasks(db_session, workspace_id="ws-1")
    by_status = await list_tasks(db_session, statuses=[TaskStatus.BACKLOG])
    combined = await list_tasks(db_session, workspace_id="ws-1", statuses=[TaskStatus.NEW])

    assert {task.id for task in by_workspace} == {plan_in_ws.id, implement_in_ws.id}
    assert implement_in_ws.id in {task.id for task in by_status}
    assert plan_in_ws.id not in {task.id for task in by_status}
    assert [task.id for task in combined] == [plan_in_ws.id]


async def test_retry_after_error(db_session: AsyncSession) -> None:
    task = await _implement(db_session)
    await change_status(db_session, task.id, TaskStatus.ACTIVE, source=TaskEventSource.WORKER)
    await change_status(db_session, task.id, TaskStatus.ERROR, source=TaskEventSource.WORKER)

    await change_status(db_session, task.id, TaskStatus.BACKLOG, source=TaskEventSource.API)

    await db_session.refresh(task)
    assert task.status == TaskStatus.BACKLOG
