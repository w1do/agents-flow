"""Таблица переходов статусов (domain/statuses.py) и доменные ошибки: сценарии task-lifecycle."""

import pytest
from harness_server.domain.errors import (
    DomainError,
    Forbidden,
    InvalidStatus,
    InvalidTransition,
    NotFound,
    UnknownWorkspace,
    UnsupportedKind,
)
from harness_server.domain.statuses import (
    INITIAL_STATUS,
    TERMINAL_STATUSES,
    TRANSITIONS,
    allowed_transitions,
    ensure_transition,
    initial_status,
    parse_status,
)
from harness_shared.tasks import TaskKind, TaskStatus

SUPPORTED_KINDS = [TaskKind.PLAN, TaskKind.IMPLEMENT]
ALLOWED_PAIRS = [
    (kind, source, target)
    for kind, table in TRANSITIONS.items()
    for source, targets in table.items()
    for target in targets
]
DISALLOWED_PAIRS = [
    (kind, source, target)
    for kind in SUPPORTED_KINDS
    for source in TaskStatus
    for target in TaskStatus
    if target not in allowed_transitions(kind, source)
]


def _reachable(kind: TaskKind) -> set[TaskStatus]:
    """Статусы, достижимые из начального по таблице переходов."""
    seen = {INITIAL_STATUS[kind]}
    frontier = [INITIAL_STATUS[kind]]
    while frontier:
        current = frontier.pop()
        for nxt in allowed_transitions(kind, current):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    return seen


@pytest.mark.parametrize(("kind", "source", "target"), ALLOWED_PAIRS)
def test_allowed_transitions_pass(kind: TaskKind, source: TaskStatus, target: TaskStatus) -> None:
    ensure_transition(kind, source, target)


@pytest.mark.parametrize(("kind", "source", "target"), DISALLOWED_PAIRS)
def test_disallowed_transitions_raise(
    kind: TaskKind, source: TaskStatus, target: TaskStatus
) -> None:
    with pytest.raises(InvalidTransition):
        ensure_transition(kind, source, target)


@pytest.mark.parametrize("kind", SUPPORTED_KINDS)
def test_every_status_reachable_from_initial(kind: TaskKind) -> None:
    mentioned = set(TRANSITIONS[kind]) | {
        target for targets in TRANSITIONS[kind].values() for target in targets
    }

    assert _reachable(kind) == mentioned


@pytest.mark.parametrize("kind", SUPPORTED_KINDS)
def test_non_terminal_statuses_have_exit(kind: TaskKind) -> None:
    for status in _reachable(kind):
        if status in TERMINAL_STATUSES[kind]:
            assert not allowed_transitions(kind, status), status
        else:
            assert allowed_transitions(kind, status), status


def test_parse_status_rejects_unknown() -> None:
    with pytest.raises(InvalidStatus):
        parse_status("completed")


def test_check_kind_unsupported() -> None:
    with pytest.raises(UnsupportedKind):
        initial_status(TaskKind.CHECK)
    with pytest.raises(UnsupportedKind):
        allowed_transitions(TaskKind.CHECK, TaskStatus.NEW)


def test_domain_error_codes() -> None:
    classes: list[type[DomainError]] = [
        InvalidTransition,
        InvalidStatus,
        UnsupportedKind,
        UnknownWorkspace,
        NotFound,
        Forbidden,
    ]

    # Машинный код уникален у каждого класса: MCP и API различают ошибки по нему.
    assert len({cls.code for cls in classes}) == len(classes)
    assert all(issubclass(cls, DomainError) for cls in classes)
    assert DomainError.code == "domain_error"
