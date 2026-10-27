from typing import Any

from sqlalchemy import Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import JSON_VALUE, Base, CreatedAt, UUIDPrimaryKey


class IdempotencyKey(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "idempotency_key"),)

    scope: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text)
    response_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[Any] = mapped_column(JSON_VALUE, nullable=False)
