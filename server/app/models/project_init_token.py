from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, CreatedAt, UUIDPrimaryKey


class ProjectInitToken(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "project_init_tokens"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
