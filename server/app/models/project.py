from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, CreatedAt, UpdatedAt, UUIDPrimaryKey


class Project(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    telegram_chat_id: Mapped[str | None] = mapped_column(Text)
    project_token_hash: Mapped[str | None] = mapped_column(Text)
