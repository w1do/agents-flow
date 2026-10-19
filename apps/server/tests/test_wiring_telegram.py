"""Адрес Bot API в композиционном корне: клиент получает TELEGRAM_API_URL (D-61)."""

import httpx
import pytest
import respx
from harness_server.settings import load_settings
from harness_server.wiring import build_adapters

pytestmark = pytest.mark.asyncio

PROXY = "https://tg-proxy.example.com"
TOKEN = "123:test-bot-token"


@respx.mock
async def test_build_adapters_routes_telegram_calls_to_configured_base_url(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_API_URL", f"{PROXY}/")
    settings = load_settings()
    route = respx.post(f"{PROXY}/bot{TOKEN}/getFile").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"file_id": "F1", "file_path": "voice/a.oga"}}
        )
    )

    async with httpx.AsyncClient() as http:
        adapters = build_adapters(settings, http)
        telegram_file = await adapters.telegram.get_file("F1")

    assert route.called
    assert telegram_file.file_path == "voice/a.oga"


@respx.mock
async def test_build_adapters_defaults_to_bot_api(valid_env: dict[str, str]) -> None:
    settings = load_settings()
    route = respx.post("https://api.telegram.org/bot123:test-bot-token/getFile").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"file_id": "F1", "file_path": "voice/a.oga"}}
        )
    )

    async with httpx.AsyncClient() as http:
        adapters = build_adapters(settings, http)
        await adapters.telegram.get_file("F1")

    assert route.called
