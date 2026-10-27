from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, UUIDPrimaryKey


class SkillCategory(UUIDPrimaryKey, Base):
    __tablename__ = "skill_categories"

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
