"""Сценарий 3 platform-config: /health без внешних вызовов, /health/ready 503 без БД."""

import asyncio

import httpx
import pytest
from asgi_lifespan import LifespanManager
from harness_server.app import create_app
from harness_server.config import load_config
from harness_server.services.context import BotContext
from harness_server.settings import load_settings


async def test_slow_recovery_does_not_block_startup_or_shutdown(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def blocked_recovery(bot: BotContext) -> int:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
        return 0

    monkeypatch.setattr("harness_server.services.server_recovery.recover_pending", blocked_recovery)
    settings = load_settings()
    app = create_app(settings, load_config(settings.harness_config))

    async with (
        LifespanManager(app, startup_timeout=1, shutdown_timeout=1),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await asyncio.wait_for(started.wait(), timeout=1)
        assert (await client.get("/health")).status_code == 200
        assert not stopped.is_set()

    assert stopped.is_set()


async def test_health_ok_and_ready_503_when_database_unreachable(valid_env: dict[str, str]) -> None:
    settings = load_settings()
    app = create_app(settings, load_config(settings.harness_config))

    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        live = await client.get("/health")
        ready = await client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "database": False}
    # Детали подключения (хост, порт) не должны уходить клиенту.
    assert "127.0.0.1" not in ready.text


async def test_api_docs_are_disabled(valid_env: dict[str, str]) -> None:
    # Публичный домен не должен отдавать схему API и Swagger (S8).
    settings = load_settings()
    app = create_app(settings, load_config(settings.harness_config))

    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        docs = await client.get("/docs")
        openapi = await client.get("/openapi.json")
        redoc = await client.get("/redoc")

    assert docs.status_code == 404
    assert openapi.status_code == 404
    assert redoc.status_code == 404


async def test_ready_200_when_database_available(
    valid_env: dict[str, str], database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    settings = load_settings()
    app = create_app(settings, load_config(settings.harness_config))

    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        ready = await client.get("/health/ready")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": True}
