"""Песочницы и токены задач. Значение токена не хранится, только хеш (mvp-06)."""

import uuid
from datetime import datetime

from harness_shared.sandboxes import AgentRole, SandboxStatus
from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from harness_server.db.base import Base, TimestampMixin, enum_check, enum_type
from harness_server.db.ids import uuid7


class Sandbox(TimestampMixin, Base):
    """Песочница, созданная вручную; provider_id выдаёт провайдер (Novita)."""

    __tablename__ = "sandboxes"
    __table_args__ = (
        enum_check("status", SandboxStatus),
        UniqueConstraint("provider_id", name="uq_sandboxes_provider_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[SandboxStatus] = mapped_column(enum_type(SandboxStatus), nullable=False)
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    profile_version: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TaskToken(Base):
    """Токен агента для задачи. В БД — только token_hash; сам токен выдаётся один раз (mvp-06)."""

    __tablename__ = "task_tokens"
    __table_args__ = (
        enum_check("role", AgentRole),
        UniqueConstraint("token_hash", name="uq_task_tokens_token_hash"),
        Index("ix_task_tokens_task_id", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[AgentRole] = mapped_column(enum_type(AgentRole), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
