"""Живая проверка маршрутизатора Polza: реальный ключ и модель владельца, по умолчанию пропуск.

Запуск: LIVE_POLZA_API_KEY=… LIVE_POLZA_MODEL=… uv run pytest -m live
apps/server/tests/test_polza_live.py.
Ключ и модель не хранятся в репозитории. Без переменных тест пропускается.
"""

import os

import httpx
import pytest
from harness_server.adapters.polza import POLZA_API_URL, PolzaRouter
from harness_server.config import RepoConfig, WorkspaceConfig
from harness_server.services.routing import build_system_prompt, parse_decision
from harness_shared.routing import CommandClass

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]

WORKSPACES = (
    WorkspaceConfig(
        id="demo",
        name="Демо-проект",
        voice_aliases=[],
        repo=RepoConfig(provider="gitlab", project="group/demo"),
    ),
    WorkspaceConfig(
        id="shop",
        name="Магазин",
        voice_aliases=[],
        repo=RepoConfig(provider="gitlab", project="group/shop"),
    ),
)


async def test_live_routing_classifies_work_and_status() -> None:
    key = os.environ.get("LIVE_POLZA_API_KEY")
    model = os.environ.get("LIVE_POLZA_MODEL")
    if not key or not model:
        pytest.skip("нужны LIVE_POLZA_API_KEY и LIVE_POLZA_MODEL")
    url = os.environ.get("LIVE_POLZA_URL") or POLZA_API_URL
    system_prompt = build_system_prompt(WORKSPACES)

    async with httpx.AsyncClient() as http:
        router = PolzaRouter(url, key, model, http)
        work_reply = await router.complete(
            system_prompt=system_prompt,
            user_text="сделай авторизацию по email в магазине",
        )
        status_reply = await router.complete(
            system_prompt=system_prompt,
            user_text="какие задачи открыты",
        )

    work = parse_decision(work_reply.content)
    status = parse_decision(status_reply.content)
    assert work is not None
    assert work.command_class is CommandClass.WORK
    assert status is not None
    assert status.command_class is CommandClass.STATUS  # путь выбирает сервер, тест — только класс
