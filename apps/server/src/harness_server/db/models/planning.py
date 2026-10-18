"""Планирование: маршрутизация, пункты спецификации, чекпоинты (ARCHITECTURE.md §3)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from harness_server.db.base import Base, TimestampMixin
from harness_server.db.ids import uuid7


class Routing(Base):
    """Решение маршрутизации голосовой или текстовой задачи (ТЗ §5)."""

    __tablename__ = "routings"
    __table_args__ = (Index("ix_routings_task_id", "task_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    command_class: Mapped[str] = mapped_column(String(32), nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb", default=list
    )
    chosen_workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Checkpoint(Base):
    """Чекпоинт агента: сводка, файлы и следующий шаг. diff хранится только после редактирования."""

    __tablename__ = "checkpoints"
    __table_args__ = (Index("ix_checkpoints_task_id", "task_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    files: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb", default=list
    )
    diff_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SpecItem(TimestampMixin, Base):
    """Пункт спецификации OpenSpec в workspace. Значения status задаёт mvp-08, CHECK нет."""

    __tablename__ = "spec_items"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "change_id", "key", name="uq_spec_items_workspace_change_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    change_id: Mapped[str] = mapped_column(String(128), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    last_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("checkpoints.id", ondelete="SET NULL"), nullable=True
    )
