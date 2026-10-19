"""Решение маршрутизации команды: класс, уверенность, кандидаты workspace (mvp-05, D-31…D-33).

Ответ модели — недоверенный вход: модель только предлагает, путь выбирает сервер.
Значения enum совпадают с CHECK в таблице routings (D-22).
"""

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

TITLE_MAX_LEN: Final = 80
# Больше кандидатов модель не возвращает осмысленно; длинный список — признак сбоя.
MAX_MODEL_CANDIDATES: Final = 20


class CommandClass(StrEnum):
    """Класс голосовой или текстовой команды в MVP (ТЗ §5.0)."""

    WORK = "work"
    STATUS = "status"
    UNKNOWN = "unknown"


class RoutingDecisionKind(StrEnum):
    """Путь сервера: auto — по классу; clarify — уточнение; fallback — без модели."""

    AUTO = "auto"
    CLARIFY = "clarify"
    FALLBACK = "fallback"


class WorkspaceCandidate(BaseModel):
    """Кандидат workspace из ответа модели. id сверяется с конфигом на сервере."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    score: float = Field(ge=0.0, le=1.0)


class RoutingDecision(BaseModel):
    """JSON модели {class, confidence, workspaces: [{id, score}], title}.

    Лишние поля игнорируются.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    command_class: CommandClass = Field(alias="class")
    confidence: float = Field(ge=0.0, le=1.0)
    workspaces: list[WorkspaceCandidate] = Field(
        default_factory=list, max_length=MAX_MODEL_CANDIDATES
    )
    title: str = ""

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, value: str) -> str:
        # Заголовок модели в MVP не показывается (D-34): только схлопываем пробелы и режем длину.
        return " ".join(value.split())[:TITLE_MAX_LEN]
