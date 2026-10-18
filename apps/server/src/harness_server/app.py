"""Фабрика FastAPI-приложения. Без глобального состояния: настройки и конфиг передаются явно."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from harness_server.api.health import router as health_router
from harness_server.api.tasks import router as tasks_router
from harness_server.config import HarnessConfig
from harness_server.db.session import create_engine, create_session_factory
from harness_server.settings import Settings


def create_app(settings: Settings, config: HarnessConfig) -> FastAPI:
    """Создаёт приложение. Engine БД создаётся в lifespan и закрывается при остановке.

    Тесты передают свои settings и config, поэтому подключение к БД можно подменить.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url.get_secret_value())
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.settings = settings
        app.state.config = config
        try:
            yield
        finally:
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
    return app
