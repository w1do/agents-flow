"""Очередь claim_next_task на настоящих коммитах (committed_session_factory): сценарии
task-lifecycle."""

import asyncio
from uuid import UUID

import pytest
from harness_server.db.models import Sandbox, Task
from harness_server.domain.errors import InvalidTransition
from harness_server.services.tasks import (
    claim_next_task,
    create_task,
    list_task_events,
    lock_next_task,
)
from harness_shared.sandboxes import SandboxStatus
from harness_shared.tasks import TaskEventSource, TaskKind, TaskSource, TaskStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

Factory = async_sessionmaker[AsyncSession]


async def _implement(factory: Factory, *, priority: int = 0) -> UUID:
    async with factory() as session:
        task = await create_task(
            session,
            kind=TaskKind.IMPLEMENT,
            text="реализация",
            source=TaskSource.API,
            known_workspace_ids=[],
            priority=priority,
        )
        return task.id


async def _claim(factory: Factory) -> Task | None:
    async with factory() as session:
        return await claim_next_task(
            session,
            kind=TaskKind.IMPLEMENT,
            from_status=TaskStatus.BACKLOG,
            to_status=TaskStatus.ACTIVE,
        )


async def test_claim_returns_highest_priority_then_oldest(
    committed_session_factory: Factory,
) -> None:
    low = await _implement(committed_session_factory, priority=0)
    first_high = await _implement(committed_session_factory, priority=5)
    second_high = await _implement(committed_session_factory, priority=5)

    claimed_ids = []
    for _ in range(3):
        task = await _claim(committed_session_factory)
        assert task is not None
        claimed_ids.append(task.id)

    assert claimed_ids == [first_high, second_high, low]
    assert await _claim(committed_session_factory) is None


async def test_claim_skips_locked_task(committed_session_factory: Factory) -> None:
    task_id = await _implement(committed_session_factory)

    async with committed_session_factory() as blocker:
        # Открытая транзакция блокирует строку: очередь должна её пропустить, а не ждать.
        await blocker.execute(select(Task).where(Task.id == task_id).with_for_update())

        assert await _claim(committed_session_factory) is None

        await blocker.rollback()

    claimed = await _claim(committed_session_factory)
    assert claimed is not None
    assert claimed.id == task_id
    assert claimed.status == TaskStatus.ACTIVE
    async with committed_session_factory() as session:
        events = await list_task_events(session, task_id)
    assert len(events) == 1
    assert events[0].source == TaskEventSource.WORKER


async def test_two_concurrent_claims_get_one_task(committed_session_factory: Factory) -> None:
    await _implement(committed_session_factory)

    results = await asyncio.gather(
        _claim(committed_session_factory), _claim(committed_session_factory)
    )

    assert sum(result is not None for result in results) == 1


async def test_two_concurrent_claims_get_different_tasks(
    committed_session_factory: Factory,
) -> None:
    await _implement(committed_session_factory)
    await _implement(committed_session_factory)

    first, second = await asyncio.gather(
        _claim(committed_session_factory), _claim(committed_session_factory)
    )

    assert first is not None
    assert second is not None
    assert first.id != second.id


async def test_claim_rejects_invalid_transition(committed_session_factory: Factory) -> None:
    await _implement(committed_session_factory)

    async with committed_session_factory() as session:
        with pytest.raises(InvalidTransition):
            await claim_next_task(
                session,
                kind=TaskKind.IMPLEMENT,
                from_status=TaskStatus.BACKLOG,
                to_status=TaskStatus.READY,
            )


async def test_claim_ignores_other_kind_and_status(committed_session_factory: Factory) -> None:
    await _implement(committed_session_factory)
    async with committed_session_factory() as session:
        await create_task(
            session,
            kind=TaskKind.PLAN,
            text="план",
            source=TaskSource.API,
            known_workspace_ids=[],
        )

    # Единственная implement-задача уже будет захвачена, plan-задача другого kind.
    first = await _claim(committed_session_factory)
    assert first is not None
    assert await _claim(committed_session_factory) is None

    async with committed_session_factory() as session:
        plan = await claim_next_task(
            session,
            kind=TaskKind.PLAN,
            from_status=TaskStatus.NEW,
            to_status=TaskStatus.CHOOSING,
        )
    assert plan is not None
    assert plan.kind == TaskKind.PLAN


async def test_lock_without_status_change_skips_task_pinned_to_sandbox(
    committed_session_factory: Factory,
) -> None:
    # Задача уже закреплена за песочницей (current_task_id): без смены статуса её не берут.
    pinned = await _implement(committed_session_factory)
    free = await _implement(committed_session_factory)
    async with committed_session_factory() as session:
        session.add(
            Sandbox(
                provider_id="sbx-queue",
                agent_type="claude-code",
                status=SandboxStatus.ACTIVE,
                current_task_id=pinned,
            )
        )
        await session.commit()

    async with committed_session_factory() as session:
        task = await lock_next_task(
            session,
            kind=TaskKind.IMPLEMENT,
            from_status=TaskStatus.BACKLOG,
            to_status=None,
        )
        assert task is not None
        assert task.id == free
        assert task.status == TaskStatus.BACKLOG
        await session.commit()

    async with committed_session_factory() as session:
        events = await list_task_events(session, free)
    # Статус не менялся, событие записано с текущим статусом задачи.
    assert [event.status for event in events] == [TaskStatus.BACKLOG]
