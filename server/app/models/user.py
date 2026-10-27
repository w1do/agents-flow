from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, CreatedAt, UUIDPrimaryKey


class User(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
