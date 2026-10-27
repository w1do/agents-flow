from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import JSON_VALUE, Base, CreatedAt, UUIDPrimaryKey


class TaskEvent(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "task_events"
    __table_args__ = (
        UniqueConstraint("task_id", "event_id"),
        Index("ix_task_events_task_id_created_at", "task_id", "created_at"),
    )

    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"))
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id"))
    event_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE, nullable=True)
