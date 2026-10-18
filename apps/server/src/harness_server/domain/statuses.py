"""Единственное место правил статусов задачи: таблица переходов по kind (ТЗ v5, D-25).

Сервисы вызывают ensure_transition до записи в БД; переходы в CHECK или триггерах не задаются, чтобы
ошибка оставалась доменной (invalid_transition), а не IntegrityError. Kind check в таблицах
намеренно нет.
"""

from collections.abc import Mapping
from typing import Final

from harness_shared.tasks import TaskKind, TaskStatus

from harness_server.domain.errors import InvalidStatus, InvalidTransition, UnsupportedKind

TRANSITIONS: Final[Mapping[TaskKind, Mapping[TaskStatus, frozenset[TaskStatus]]]] = {
    TaskKind.PLAN: {
        TaskStatus.NEW: frozenset({TaskStatus.CHOOSING}),
        TaskStatus.CHOOSING: frozenset({TaskStatus.PLANNING, TaskStatus.TRASH}),
        TaskStatus.PLANNING: frozenset({TaskStatus.READY, TaskStatus.ERROR}),
    },
    TaskKind.IMPLEMENT: {
        TaskStatus.BACKLOG: frozenset({TaskStatus.ACTIVE}),
        TaskStatus.ACTIVE: frozenset({TaskStatus.TESTING, TaskStatus.ERROR}),
        TaskStatus.TESTING: frozenset({TaskStatus.READY, TaskStatus.ERROR}),
        TaskStatus.READY: frozenset({TaskStatus.MERGED}),
        # error → backlog: повтор задачи после сбоя, а не откат к активной работе.
        TaskStatus.ERROR: frozenset({TaskStatus.BACKLOG}),
    },
}

INITIAL_STATUS: Final[Mapping[TaskKind, TaskStatus]] = {
    TaskKind.PLAN: TaskStatus.NEW,
    TaskKind.IMPLEMENT: TaskStatus.BACKLOG,
}

TERMINAL_STATUSES: Final[Mapping[TaskKind, frozenset[TaskStatus]]] = {
    TaskKind.PLAN: frozenset({TaskStatus.READY, TaskStatus.ERROR, TaskStatus.TRASH}),
    TaskKind.IMPLEMENT: frozenset({TaskStatus.MERGED}),
}


def parse_status(value: TaskStatus | str) -> TaskStatus:
    """Превращает строку в TaskStatus. Значение вне набора ТЗ — InvalidStatus, БД не меняется."""
    try:
        return TaskStatus(value)
    except ValueError:
        raise InvalidStatus(str(value)) from None


def initial_status(kind: TaskKind) -> TaskStatus:
    """Статус новой задачи данного kind. Kind без начального статуса — UnsupportedKind."""
    try:
        return INITIAL_STATUS[kind]
    except KeyError:
        raise UnsupportedKind(kind) from None


def allowed_transitions(kind: TaskKind, from_status: TaskStatus) -> frozenset[TaskStatus]:
    """Статусы, в которые можно перейти из from_status. Статус без выходов — пустое множество."""
    try:
        table = TRANSITIONS[kind]
    except KeyError:
        raise UnsupportedKind(kind) from None
    return table.get(from_status, frozenset())


def ensure_transition(kind: TaskKind, from_status: TaskStatus, to_status: TaskStatus) -> None:
    """Проверяет переход по таблице. Недопустимый — InvalidTransition."""
    if to_status not in allowed_transitions(kind, from_status):
        raise InvalidTransition(kind, from_status, to_status)
