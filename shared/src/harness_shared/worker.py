"""Контракт HTTP-канала worker: только разрешённые поля, без значений ключей."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from harness_shared.projects import Workspace
from harness_shared.sandboxes import AgentRole
from harness_shared.tasks import TaskOut


class ClaimIn(BaseModel):
    """Worker выбирает тип, правила очереди и роль определяет сервер."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["plan", "implement"]
    provider_id: str | None = Field(default=None, min_length=1, max_length=128)


class ClaimOut(BaseModel):
    """Токен выдаётся один раз; в БД хранится только хеш."""

    model_config = ConfigDict(extra="forbid")
    task: TaskOut
    project: Workspace
    task_token: str
    role: AgentRole
    expires_at: datetime
