from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, UUIDPrimaryKey


class TaskSkillSnapshot(UUIDPrimaryKey, Base):
    __tablename__ = "task_skill_snapshots"
    __table_args__ = (UniqueConstraint("task_id", "skill_id"),)

    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"))
    skill_id: Mapped[UUID] = mapped_column(ForeignKey("skills.id"))
    skill_name: Mapped[str] = mapped_column(Text)
    skill_version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(Text)
