"""Health-эндпоинты. /health не ходит наружу; /health/ready проверяет БД с коротким таймаутом."""

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from harness_shared.health import HealthResponse, ReadyResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

READY_TIMEOUT_SEC = 2.0


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Живость процесса. Не обращается к БД и другим системам."""
    return HealthResponse(status="ok")


@router.get("/health/ready", responses={503: {"model": ReadyResponse}})
async def ready(request: Request) -> JSONResponse:
    """Готовность: 200 при доступной БД, иначе 503. Детали подключения не уходят наружу."""
    engine: AsyncEngine = request.app.state.engine
    try:
        await asyncio.wait_for(_ping_database(engine), timeout=READY_TIMEOUT_SEC)
    except Exception as exc:
        # Только тип ошибки: текст исключения asyncpg может содержать хост и имя пользователя.
        logger.warning("readiness: database unavailable (%s)", type(exc).__name__)
        unavailable = ReadyResponse(status="unavailable", database=False)
        return JSONResponse(status_code=503, content=unavailable.model_dump())
    available = ReadyResponse(status="ready", database=True)
    return JSONResponse(status_code=200, content=available.model_dump())


async def _ping_database(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
