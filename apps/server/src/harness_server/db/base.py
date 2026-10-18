"""Базовый класс ORM, имена ограничений и типы перечислений (D-22).

Имена ограничений задаются явно или через NAMING_CONVENTION: миграция 0001 пишет их литералами,
поэтому alembic check сравнивает одни и те же имена.
"""

from datetime import datetime
from enum import StrEnum
from typing import Final

import sqlalchemy as sa
from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Базовый класс всех моделей. Метаданные с naming convention — основа для target_metadata."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_type(enum_cls: type[StrEnum]) -> sa.Enum:
    """Тип колонки VARCHAR(16) со значениями enum, а не именами (D-22).

    CHECK объявляется отдельно через enum_check. Нативный ENUM Postgres не используется:
    его нельзя изменить внутри транзакции миграции.
    """
    return sa.Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=16,
        validate_strings=True,
        values_callable=lambda cls: [member.value for member in cls],
    )


def enum_check(column: str, enum_cls: type[StrEnum]) -> sa.CheckConstraint:
    """CHECK column IN (...) с именем ck_<table>_<column>. Значения — константы enum, не ввод."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return sa.CheckConstraint(f"{column} IN ({values})", name=column)


class TimestampMixin:
    """created_at и updated_at; время ставит БД (now() — начало транзакции, см. design)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
