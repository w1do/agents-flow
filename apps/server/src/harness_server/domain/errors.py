"""Ошибки домена. MCP и API переводят их в ответы по полю code (CLAUDE.md §4).

Сообщения не содержат текста задачи и значений секретов: они попадают в ответы и логи.
"""

from typing import ClassVar

from harness_shared.tasks import TaskKind, TaskStatus


class DomainError(Exception):
    """Базовая ошибка домена. code — машинный код для API/MCP; message без секретов."""

    code: ClassVar[str] = "domain_error"


class InvalidTransition(DomainError):
    """Переход между статусами не разрешён таблицей для данного kind."""

    code = "invalid_transition"

    def __init__(self, kind: TaskKind, from_status: TaskStatus, to_status: TaskStatus) -> None:
        super().__init__(f"переход {from_status} → {to_status} недопустим для {kind}")
        self.kind = kind
        self.from_status = from_status
        self.to_status = to_status


class InvalidStatus(DomainError):
    """Значение не входит в набор статусов ТЗ v5."""

    code = "invalid_status"

    def __init__(self, value: str) -> None:
        super().__init__(f"неизвестный статус: {value!r}")
        self.value = value


class UnsupportedKind(DomainError):
    """Тип задачи пока не поддерживается (в MVP — check)."""

    code = "unsupported_kind"

    def __init__(self, kind: TaskKind) -> None:
        super().__init__(f"тип задачи {kind} пока не поддерживается")
        self.kind = kind


class UnknownWorkspace(DomainError):
    """workspace_id нет в harness.yaml."""

    code = "unknown_workspace"

    def __init__(self, workspace_id: str) -> None:
        super().__init__("неизвестный workspace")
        self.workspace_id = workspace_id


class NotFound(DomainError):
    """Сущность не найдена. entity_id не содержит данных, кроме идентификатора."""

    code = "not_found"

    def __init__(self, entity: str, entity_id: object) -> None:
        super().__init__(f"{entity} не найден(а): {entity_id}")
        self.entity = entity
        self.entity_id = entity_id


class Forbidden(DomainError):
    """Действие запрещено текущему субъекту. Используется начиная с mvp-07."""

    code = "forbidden"
