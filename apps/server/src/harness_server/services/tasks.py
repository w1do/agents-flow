"""Единственное место правил задачи: создание, смена статуса, лента событий и очередь.

Каждая публичная функция — одна транзакция и сама делает commit (D-24): статус и событие пишутся
атомарно, а входы не решают, когда коммитить. Все функции async, session первым аргументом.
В логах — только идентификаторы и статусы, без текста задачи (он может содержать персональные
данные).
"""

import logging
from collections.abc import Collection
from uuid import UUID

from harness_shared.tasks import TaskEventSource, TaskKind, TaskSource, TaskStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import Project, Sandbox, SpecItem, Task, TaskEvent, TaskToken
from harness_server.domain.errors import NotFound, UnknownWorkspace
from harness_server.domain.statuses import (
    ensure_transition,
    initial_status,
    parse_status,
)

logger = logging.getLogger(__name__)


async def _commit(session: AsyncSession, *objects: Task | TaskEvent) -> None:
    """Коммит и перечитывание серверных полей (created_at, updated_at).

    Перечитывание нужно, чтобы не делать ленивую загрузку в async-сессии."""
    await session.commit()
    for obj in objects:
        await session.refresh(obj)


async def create_task(
    session: AsyncSession,
    *,
    kind: TaskKind,
    text: str,
    source: TaskSource,
    known_workspace_ids: Collection[str],
    workspace_id: str | None = None,
    parent_id: UUID | None = None,
    spec_item_id: UUID | None = None,
    priority: int = 0,
) -> Task:
    """Создаёт задачу в начальном статусе kind. Событие не пишется: лента — смены статусов и отчёты.

    Бросает UnsupportedKind (check в MVP), UnknownWorkspace, NotFound (родитель или пункт
    спецификации).
    """
    status = initial_status(kind)
    if workspace_id is not None and workspace_id not in known_workspace_ids:
        raise UnknownWorkspace(workspace_id)
    if parent_id is not None and await session.get(Task, parent_id) is None:
        raise NotFound("task", parent_id)
    if spec_item_id is not None and await session.get(SpecItem, spec_item_id) is None:
        raise NotFound("spec_item", spec_item_id)

    task = Task(
        kind=kind,
        text=text,
        status=status,
        source=source,
        workspace_id=workspace_id,
        parent_id=parent_id,
        spec_item_id=spec_item_id,
        priority=priority,
    )
    session.add(task)
    await _commit(session, task)
    logger.info("task created id=%s kind=%s status=%s", task.id, kind, status)
    return task


async def get_task(session: AsyncSession, task_id: UUID) -> Task:
    """Возвращает задачу по id. Бросает NotFound, если её нет."""
    task = await session.get(Task, task_id)
    if task is None:
        raise NotFound("task", task_id)
    return task


async def list_task_events(session: AsyncSession, task_id: UUID) -> list[TaskEvent]:
    """Лента событий задачи в хронологическом порядке (created_at, затем id)."""
    result = await session.execute(
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id)
        .order_by(TaskEvent.created_at, TaskEvent.id)
    )
    return list(result.scalars().all())


async def list_tasks(
    session: AsyncSession,
    *,
    workspace_id: str | None = None,
    statuses: Collection[TaskStatus] | None = None,
    limit: int = 100,
) -> list[Task]:
    """Задачи с необязательными фильтрами по workspace и статусам, по возрастанию created_at."""
    stmt = select(Task)
    if workspace_id is not None:
        stmt = stmt.where(Task.workspace_id == workspace_id)
    if statuses is not None:
        stmt = stmt.where(Task.status.in_(list(statuses)))
    result = await session.execute(stmt.order_by(Task.created_at, Task.id).limit(limit))
    return list(result.scalars().all())


async def change_status(
    session: AsyncSession,
    task_id: UUID,
    to_status: TaskStatus | str,
    *,
    source: TaskEventSource,
    text: str | None = None,
) -> Task:
    """Меняет статус по таблице переходов и пишет событие в той же транзакции.

    Строка блокируется FOR UPDATE, чтобы два параллельных изменения не потеряли переход. Ошибки
    (InvalidStatus, NotFound, InvalidTransition) возникают до записи, поэтому ничего не коммитится.
    """
    target = parse_status(to_status)
    # populate_existing: после получения блокировки читается актуальный статус строки, а не кэш
    # сессии.
    result = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFound("task", task_id)
    ensure_transition(task.kind, task.status, target)

    task.status = target
    event = TaskEvent(task_id=task.id, status=target, text=text, source=source)
    session.add(event)
    await _commit(session, task, event)
    logger.info("task status changed id=%s to=%s source=%s", task.id, target, source)
    return task


async def select_workspace(
    session: AsyncSession,
    task_id: UUID,
    workspace_id: str,
    *,
    known_workspace_ids: Collection[str],
    source: TaskEventSource,
    text: str | None = None,
) -> Task:
    """Назначает workspace и переводит задачу choosing → planning одной транзакцией.

    Бросает UnknownWorkspace, NotFound, InvalidTransition (задача уже не в choosing) — до записи.
    Строка блокируется FOR UPDATE: два одновременных нажатия кнопки не назначат два workspace.
    """
    if workspace_id not in known_workspace_ids:
        raise UnknownWorkspace(workspace_id)
    # populate_existing: статус читается после блокировки, а не из кэша сессии.
    result = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFound("task", task_id)
    ensure_transition(task.kind, task.status, TaskStatus.PLANNING)

    task.workspace_id = workspace_id
    task.status = TaskStatus.PLANNING
    event = TaskEvent(task_id=task.id, status=TaskStatus.PLANNING, text=text, source=source)
    session.add(event)
    await _commit(session, task, event)
    logger.info("task workspace selected id=%s workspace=%s", task.id, workspace_id)
    return task


async def add_event(
    session: AsyncSession, task_id: UUID, *, text: str, source: TaskEventSource
) -> TaskEvent:
    """Добавляет отчёт к задаче без смены статуса: событие получает текущий статус задачи."""
    task = await get_task(session, task_id)
    event = TaskEvent(task_id=task.id, status=task.status, text=text, source=source)
    session.add(event)
    await _commit(session, event)
    return event


async def lock_next_task(
    session: AsyncSession,
    *,
    kind: TaskKind,
    from_status: TaskStatus,
    to_status: TaskStatus | None,
    source: TaskEventSource = TaskEventSource.WORKER,
    text: str | None = None,
    worker_api: bool = False,
) -> Task | None:
    """Блокирует следующую задачу очереди и пишет событие; БЕЗ commit (mvp-06, D-24 — исключение).

    Только для композиции внутри сервиса, который сам владеет транзакцией: например, резервирование
    песочницы и задачи одной транзакцией (services/sandboxes). Вызывающий обязан закоммитить или
    откатить сессию; блокировки строки держатся до этого. Публичный вход без композиции —
    claim_next_task, он коммитит сам.

    to_status=None: задача берётся без смены статуса (например, plan остаётся в planning до
    этапа mvp-08). Такая выборка исключает задачи, уже закреплённые за песочницей
    (sandboxes.current_task_id), и пишет событие с текущим статусом задачи.

    Выбор — наибольший priority, затем самая ранняя; FOR UPDATE SKIP LOCKED пропускает строки,
    занятые другими транзакциями. Возвращает None, если подходящих задач нет.
    """
    if to_status is not None:
        ensure_transition(kind, from_status, to_status)
    stmt = select(Task).where(Task.kind == kind, Task.status == from_status)
    if worker_api:
        active_project = (
            select(Project.id)
            .where(Project.id == Task.workspace_id, Project.status == "active")
            .exists()
        )
        claimed = (
            select(TaskToken.id)
            .where(TaskToken.task_id == Task.id, TaskToken.revoked_at.is_(None))
            .exists()
        )
        stmt = stmt.where(active_project, ~claimed)
    if to_status is None:
        # Задача, уже закреплённая за песочницей, второй раз не берётся.
        pinned = select(Sandbox.id).where(Sandbox.current_task_id == Task.id).exists()
        stmt = stmt.where(~pinned)
    stmt = (
        stmt.order_by(Task.priority.desc(), Task.created_at, Task.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    task = (await session.execute(stmt)).scalar_one_or_none()
    if task is None:
        return None

    if to_status is not None:
        task.status = to_status
    event = TaskEvent(task_id=task.id, status=task.status, text=text, source=source)
    session.add(event)
    return task


async def claim_next_task(
    session: AsyncSession,
    *,
    kind: TaskKind,
    from_status: TaskStatus,
    to_status: TaskStatus,
    source: TaskEventSource = TaskEventSource.WORKER,
    text: str | None = None,
) -> Task | None:
    """Захватывает следующую задачу из очереди: переход, событие и commit одной транзакцией.

    Выборка и её правила — в lock_next_task. Блокировки снимаются commit внутри функции.
    Долгую работу вызывающий выполняет после возврата, вне транзакции. Возвращает None, если
    подходящих задач нет.

    Возвращённая задача перечитана через refresh, и сессия при этом снова открывает транзакцию
    (autobegin) без блокировок. Вызывающий должен закрыть сессию сразу после claim, до долгой
    работы; это учитывается в mvp-06.
    """
    ensure_transition(kind, from_status, to_status)
    task = await lock_next_task(
        session,
        kind=kind,
        from_status=from_status,
        to_status=to_status,
        source=source,
        text=text,
    )
    if task is None:
        # Закрываем транзакцию, открытую выборкой, чтобы блокировок не осталось.
        await session.commit()
        return None

    await _commit(session, task)
    logger.info("task claimed id=%s to=%s", task.id, to_status)
    return task
