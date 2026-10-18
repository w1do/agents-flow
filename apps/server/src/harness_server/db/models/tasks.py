"""Задачи и лента событий.

Смена статуса пишет TaskEvent в той же транзакции (services/tasks.py, D-24)."""

import uuid
from datetime import datetime

from harness_shared.tasks import TaskEventSource, TaskKind, TaskSource, TaskStatus, TestsState
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from harness_server.db.base import Base, TimestampMixin, enum_check, enum_type
from harness_server.db.ids import uuid7


class Task(TimestampMixin, Base):
    """Задача. kind и статус — из enum, значения дублируются CHECK в БД."""

    __tablename__ = "tasks"
    __table_args__ = (
        enum_check("kind", TaskKind),
        enum_check("status", TaskStatus),
        enum_check("source", TaskSource),
        enum_check("tests_state", TestsState),
        Index("ix_tasks_queue", "kind", "status", "priority", "created_at"),
        Index("ix_tasks_workspace_id", "workspace_id"),
        Index("ix_tasks_parent_id", "parent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    kind: Mapped[TaskKind] = mapped_column(enum_type(TaskKind), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(enum_type(TaskStatus), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    source: Mapped[TaskSource] = mapped_column(enum_type(TaskSource), nullable=False)
    # use_alter: цикл tasks ↔ spec_items; FK создаётся в миграции после всех таблиц (design §10).
    spec_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("spec_items.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mr_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    tests_state: Mapped[TestsState] = mapped_column(
        enum_type(TestsState),
        nullable=False,
        server_default=TestsState.NOT_RUN.value,
        default=TestsState.NOT_RUN,
    )


class TaskEvent(Base):
    """Событие ленты: статус на момент записи, текст отчёта и источник."""

    __tablename__ = "task_events"
    __table_args__ = (
        enum_check("status", TaskStatus),
        enum_check("source", TaskEventSource),
        Index("ix_task_events_task_id_created_at", "task_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[TaskStatus] = mapped_column(enum_type(TaskStatus), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[TaskEventSource] = mapped_column(enum_type(TaskEventSource), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
