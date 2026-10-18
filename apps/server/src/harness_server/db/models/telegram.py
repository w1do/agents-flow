"""Служебные таблицы Telegram: карточка сообщения задачи и учёт входящих апдейтов (mvp-04)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from harness_server.db.base import Base, TimestampMixin


class TelegramMessage(TimestampMixin, Base):
    """Сообщение-карточка задачи в чате: PK — task_id, одна карточка на задачу."""

    __tablename__ = "telegram_messages"

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lines: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb", default=list
    )


class TelegramUpdate(Base):
    """Учёт входящих апдейтов Telegram: дубликаты отбрасываются по (kind, external_id)."""

    __tablename__ = "telegram_updates"
    __table_args__ = (CheckConstraint("kind IN ('update', 'callback')", name="kind"),)

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
