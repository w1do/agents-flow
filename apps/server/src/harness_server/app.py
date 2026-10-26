"""Фабрика FastAPI-приложения. Без глобального состояния: настройки и конфиг передаются явно."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from harness_server.api.health import router as health_router
from harness_server.api.projects import console_router as projects_console_router
from harness_server.api.projects import settings_router as projects_settings_router
from harness_server.api.tasks import router as tasks_router
from harness_server.api.telegram_webhook import router as telegram_router
from harness_server.api.worker import router as worker_router
from harness_server.api.worker_cleanup import router as worker_cleanup_router
from harness_server.api.worker_reports import router as worker_reports_router
from harness_server.api.worker_sandbox import router as worker_sandbox_router
from harness_server.config import HarnessConfig
from harness_server.db.session import create_engine, create_session_factory
from harness_server.services.server_recovery import recovery_loop
from harness_server.services.worker_heartbeat import monitor
from harness_server.settings import Settings
from harness_server.wiring import (
    BotAdapters,
    build_adapters,
    build_bot_context,
    build_http_client,
)


def create_app(
    settings: Settings, config: HarnessConfig, *, adapters: BotAdapters | None = None
) -> FastAPI:
    """Создаёт приложение. Engine БД и httpx-клиент создаются в lifespan и закрываются при выходе.

    Тесты передают свои settings, config и adapters (фейки Telegram и STT), поэтому внешние сервисы
    подменяются без глобального состояния.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url.get_secret_value())
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.settings = settings
        app.state.config = config
        http = build_http_client()
        background = asyncio.create_task(
            monitor(app.state.session_factory, settings.worker_heartbeat_timeout_sec)
        )
        recovery_task = None
        try:
            bot_adapters = adapters if adapters is not None else build_adapters(settings, http)
            app.state.bot = build_bot_context(settings, app.state.session_factory, bot_adapters)
            recovery_task = asyncio.create_task(recovery_loop(app.state.bot))
            yield
        finally:
            if recovery_task is not None:
                recovery_task.cancel()
                with suppress(asyncio.CancelledError):
                    await recovery_task
            background.cancel()
            with suppress(asyncio.CancelledError):
                await background
            await http.aclose()
            await engine.dispose()

    # Публичный домен отдаёт только рабочие эндпоинты: схема API и Swagger на этом этапе не нужны.
    app = FastAPI(
        title="agents-flow harness",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(health_router)
    app.include_router(tasks_router)
    app.include_router(projects_console_router)
    app.include_router(projects_settings_router)
    app.include_router(telegram_router)
    app.include_router(worker_router)
    app.include_router(worker_reports_router)
    app.include_router(worker_sandbox_router)
    app.include_router(worker_cleanup_router)
    return app
