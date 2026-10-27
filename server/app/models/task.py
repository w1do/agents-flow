from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import JSON_VALUE, Base, CreatedAt, UpdatedAt, UUIDPrimaryKey


class Task(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'choosing', 'planning', 'backlog', 'active', 'testing', "
            "'ready', 'merged', 'error', 'stalled', 'paused', 'trash')", name="status",
        ),
        CheckConstraint(
            "source_type IN ('web', 'telegram_text', 'telegram_voice', 'api')",
            name="source_type",
        ),
        CheckConstraint("plan_decision IN ('pending', 'approved', 'rejected')",
                        name="plan_decision"),
        Index("ix_tasks_project_id_status", "project_id", "status"),
        Index("ix_tasks_status_created_at", "status", "created_at"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    source_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="new")
    assigned_agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id"))
    lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_text: Mapped[str | None] = mapped_column(Text)
    plan_revision: Mapped[int] = mapped_column(Integer, server_default="0")
    plan_decision: Mapped[str] = mapped_column(Text, server_default="pending")
    plan_feedback: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[str | None] = mapped_column(Text)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE, nullable=True)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
