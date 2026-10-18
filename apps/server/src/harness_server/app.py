"""Фабрика FastAPI-приложения. Без глобального состояния: настройки и конфиг передаются явно."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from harness_server.api.health import router as health_router
from harness_server.api.tasks import router as tasks_router
from harness_server.api.telegram_webhook import router as telegram_router
from harness_server.config import HarnessConfig
from harness_server.db.session import create_engine, create_session_factory
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
        try:
            bot_adapters = adapters if adapters is not None else build_adapters(settings, http)
            app.state.bot = build_bot_context(
                settings, config, app.state.session_factory, bot_adapters
            )
            yield
        finally:
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
    app.include_router(telegram_router)
    return app
