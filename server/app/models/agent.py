from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, CreatedAt, UpdatedAt, UUIDPrimaryKey


class Agent(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
        CheckConstraint("status IN ('online', 'busy', 'offline')", name="status"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(Text)
    agent_token_hash: Mapped[str] = mapped_column(Text)
    repository_path_hint: Mapped[str] = mapped_column(Text)
    git_remote: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="offline")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
