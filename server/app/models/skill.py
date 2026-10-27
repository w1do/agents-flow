from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, CreatedAt, UpdatedAt, UUIDPrimaryKey


class Skill(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "skills"

    category_id: Mapped[UUID] = mapped_column(ForeignKey("skill_categories.id"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    content_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
