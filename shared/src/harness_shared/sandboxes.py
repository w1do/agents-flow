"""Перечисления песочниц и агентов. Значения совпадают с CHECK-ограничениями в БД (D-22)."""

from enum import StrEnum


class SandboxStatus(StrEnum):
    """Состояние песочницы. Переходы появятся вместе с mvp-06 (sandbox-runtime)."""

    PAUSED = "paused"
    ACTIVE = "active"
    ERROR = "error"


class AgentRole(StrEnum):
    """Роль агента, для которой выдаётся токен задачи (хранится только хеш, mvp-06)."""

    PLANNER = "planner"
    IMPLEMENTER = "implementer"
