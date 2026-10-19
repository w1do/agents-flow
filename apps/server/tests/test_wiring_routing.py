"""Сборка маршрутизатора в композиционном корне: только при ключе и модели (D-31, D-33)."""

from pathlib import Path

import httpx
import pytest
from harness_server.adapters.polza import POLZA_API_URL, PolzaRouter
from harness_server.config import load_config
from harness_server.settings import load_settings
from harness_server.wiring import build_adapters, build_bot_context
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio

POLZA_KEY = "test-polza-key-0123456789"
EXAMPLE_CONFIG = Path(__file__).resolve().parents[3] / "config" / "harness.example.yaml"


async def test_build_adapters_creates_router_when_configured(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLZA_AI_KEY", POLZA_KEY)
    monkeypatch.setenv("POLZA_AI_MODEL", "test/model")
    settings = load_settings()

    async with httpx.AsyncClient() as http:
        adapters = build_adapters(settings, http)

    assert isinstance(adapters.router, PolzaRouter)
    assert adapters.router.api_url == POLZA_API_URL
    assert POLZA_KEY not in repr(adapters.router)


async def test_build_adapters_without_key_has_no_router(valid_env: dict[str, str]) -> None:
    settings = load_settings()

    async with httpx.AsyncClient() as http:
        adapters = build_adapters(settings, http)

    assert adapters.router is None


async def test_bot_context_gets_router_and_threshold(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLZA_AI_KEY", POLZA_KEY)
    monkeypatch.setenv("POLZA_AI_MODEL", "test/model")
    monkeypatch.setenv("ROUTING_MIN_CONFIDENCE", "0.75")
    settings = load_settings()
    config = load_config(EXAMPLE_CONFIG)
    # Фабрика не подключается к БД при создании: тест не выполняет запросов.
    engine = create_async_engine("postgresql+asyncpg://u:p@127.0.0.1:1/x")
    try:
        async with httpx.AsyncClient() as http:
            adapters = build_adapters(settings, http)
            ctx = build_bot_context(settings, config, async_sessionmaker(engine), adapters)
    finally:
        await engine.dispose()

    assert ctx.router is adapters.router
    assert ctx.routing_min_confidence == 0.75
