from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, UUIDPrimaryKey


class AgentSkill(UUIDPrimaryKey, Base):
    __tablename__ = "agent_skills"
    __table_args__ = (
        UniqueConstraint("agent_id", "skill_id"),
        Index("ix_agent_skills_agent_id", "agent_id"),
    )

    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id"))
    skill_id: Mapped[UUID] = mapped_column(ForeignKey("skills.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
