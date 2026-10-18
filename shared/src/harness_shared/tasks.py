"""Задачи и их DTO. Живут в shared, чтобы сервер, консоль и MCP не дублировали типы (CLAUDE.md §4).

Значения enum совпадают с CHECK-ограничениями в БД (D-22); порядок членов задаёт порядок значений в
CHECK.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

# Текст задачи ограничен: длинный ввод из Telegram или API не должен раздувать строку и лог.
TaskText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
WorkspaceId = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class TaskKind(StrEnum):
    """Тип задачи. check — в MVP отклоняется сервисом (unsupported_kind)."""

    PLAN = "plan"
    IMPLEMENT = "implement"
    CHECK = "check"


class TaskStatus(StrEnum):
    """Статусы задачи по ТЗ v5. Переходы между ними описаны в domain/statuses.py."""

    NEW = "new"
    CHOOSING = "choosing"
    PLANNING = "planning"
    BACKLOG = "backlog"
    ACTIVE = "active"
    TESTING = "testing"
    READY = "ready"
    MERGED = "merged"
    ERROR = "error"
    STALLED = "stalled"
    PAUSED = "paused"
    TRASH = "trash"


class TaskSource(StrEnum):
    """Откуда появилась задача."""

    TELEGRAM = "telegram"
    SPEC = "spec"
    MCP = "mcp"
    API = "api"


class TaskEventSource(StrEnum):
    """Кто записал событие задачи."""

    TELEGRAM = "telegram"
    AGENT = "agent"
    WORKER = "worker"
    API = "api"


class TestsState(StrEnum):
    """Результат тестов задачи. no_tests — команды тестов нет, это не «пройдено» (CLAUDE.md §3)."""

    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    NO_TESTS = "no_tests"


class TaskCreateIn(BaseModel):
    """Тело POST /tasks. Лишние поля отклоняются, чтобы опечатка не терялась молча."""

    model_config = ConfigDict(extra="forbid")

    text: TaskText
    workspace_id: WorkspaceId | None = None


class TaskEventOut(BaseModel):
    """Событие ленты задачи."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    task_id: UUID
    status: TaskStatus
    text: str | None
    source: TaskEventSource
    created_at: datetime


class TaskOut(BaseModel):
    """Задача без ленты событий."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    kind: TaskKind
    workspace_id: str | None
    parent_id: UUID | None
    text: str
    status: TaskStatus
    priority: int
    source: TaskSource
    spec_item_id: UUID | None
    branch: str | None
    mr_url: str | None
    result: str | None
    tests_state: TestsState
    created_at: datetime
    updated_at: datetime


class TaskDetailOut(TaskOut):
    """Задача с лентой событий в хронологическом порядке."""

    events: list[TaskEventOut]
