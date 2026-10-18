"""Модели ответов health-эндпоинтов. Живут в shared, чтобы не дублироваться в консоли."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Ответ GET /health: процесс жив. Внешних проверок не делает."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class ReadyResponse(BaseModel):
    """Ответ GET /health/ready: готовность сервера к работе (сейчас — доступность БД)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "unavailable"]
    database: bool
