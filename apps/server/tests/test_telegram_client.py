"""Контрактные тесты клиента Telegram на записанных ответах (respx). Токен в тестах не настоящий."""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from harness_server.adapters.telegram import (
    FileTooLarge,
    HttpxTelegramClient,
    InlineButton,
    InlineKeyboard,
    MessageNotEditable,
    TelegramError,
    TelegramFile,
)
from harness_server.adapters.telegram import client as telegram_client

pytestmark = pytest.mark.asyncio

TOKEN = "123456:TEST-TOKEN-abcdefghijklmnopqrstuvwxyz0123"
API = "https://api.telegram.org"
BOT_URL = f"{API}/bot{TOKEN}"
CHAT_ID = 424242


def _client(http: httpx.AsyncClient) -> HttpxTelegramClient:
    return HttpxTelegramClient(TOKEN, http)


@respx.mock
async def test_send_message_posts_json_and_returns_message_id() -> None:
    route = respx.post(f"{BOT_URL}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})
    )

    async with httpx.AsyncClient() as http:
        message_id = await _client(http).send_message(CHAT_ID, "привет")

    assert message_id == 77
    assert json.loads(route.calls.last.request.content) == {"chat_id": CHAT_ID, "text": "привет"}


@respx.mock
async def test_send_message_serializes_inline_keyboard() -> None:
    route = respx.post(f"{BOT_URL}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 78}})
    )
    keyboard = InlineKeyboard(
        rows=((InlineButton(text="Демо-проект", callback_data="ws:abc:demo"),),)
    )

    async with httpx.AsyncClient() as http:
        await _client(http).send_message(CHAT_ID, "текст", reply_markup=keyboard)

    body = json.loads(route.calls.last.request.content)
    assert body["reply_markup"] == {
        "inline_keyboard": [[{"text": "Демо-проект", "callback_data": "ws:abc:demo"}]]
    }


@respx.mock
async def test_api_error_raises_telegram_error_without_token() -> None:
    respx.post(f"{BOT_URL}/sendMessage").mock(
        return_value=httpx.Response(
            400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
        )
    )

    async with httpx.AsyncClient() as http:
        client = _client(http)
        with pytest.raises(TelegramError) as info:
            await client.send_message(CHAT_ID, "текст")

    assert info.value.error_code == 400
    assert "chat not found" in str(info.value)
    assert TOKEN not in str(info.value)
    assert TOKEN not in repr(info.value)
    assert TOKEN not in repr(client)


@respx.mock
async def test_network_error_does_not_leak_token() -> None:
    respx.post(f"{BOT_URL}/sendMessage").mock(
        side_effect=httpx.ConnectError(f"cannot connect to {BOT_URL}/sendMessage")
    )

    async with httpx.AsyncClient() as http:
        client = _client(http)
        with pytest.raises(TelegramError) as info:
            await client.send_message(CHAT_ID, "текст")

    assert info.value.error_code is None
    assert TOKEN not in str(info.value)
    assert TOKEN not in repr(info.value)
    assert TOKEN not in repr(client)


@respx.mock
async def test_edit_not_modified_is_ignored() -> None:
    respx.post(f"{BOT_URL}/editMessageText").mock(
        return_value=httpx.Response(
            400,
            json={
                "ok": False,
                "error_code": 400,
                "description": "Bad Request: message is not modified: specified new content",
            },
        )
    )

    async with httpx.AsyncClient() as http:
        await _client(http).edit_message_text(CHAT_ID, 100, "тот же текст")


@pytest.mark.parametrize(
    "description",
    [
        "Bad Request: message can't be edited",
        "Bad Request: message to edit not found",
        "Bad Request: MESSAGE_ID_INVALID",
    ],
)
@respx.mock
async def test_edit_not_editable_raises_message_not_editable(description: str) -> None:
    respx.post(f"{BOT_URL}/editMessageText").mock(
        return_value=httpx.Response(
            400, json={"ok": False, "error_code": 400, "description": description}
        )
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(MessageNotEditable):
            await _client(http).edit_message_text(CHAT_ID, 100, "текст")


@respx.mock
async def test_edit_other_error_is_raised() -> None:
    respx.post(f"{BOT_URL}/editMessageText").mock(
        return_value=httpx.Response(
            400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
        )
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(TelegramError) as info:
            await _client(http).edit_message_text(CHAT_ID, 100, "текст")

    assert not isinstance(info.value, MessageNotEditable)


@respx.mock
async def test_answer_callback_query() -> None:
    route = respx.post(f"{BOT_URL}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )

    async with httpx.AsyncClient() as http:
        await _client(http).answer_callback_query("4242000000000000001", text="проект уже выбран")

    assert json.loads(route.calls.last.request.content) == {
        "callback_query_id": "4242000000000000001",
        "text": "проект уже выбран",
    }


@respx.mock
async def test_get_file_returns_path_and_size() -> None:
    respx.post(f"{BOT_URL}/getFile").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "file_id": "VOICE_FILE_1",
                    "file_unique_id": "VOICE_UNIQUE_1",
                    "file_size": 2048,
                    "file_path": "voice/file_1.oga",
                },
            },
        )
    )

    async with httpx.AsyncClient() as http:
        result = await _client(http).get_file("VOICE_FILE_1")

    assert result == TelegramFile("VOICE_FILE_1", "voice/file_1.oga", 2048)


@respx.mock
async def test_download_file_uses_file_url() -> None:
    route = respx.get(f"{API}/file/bot{TOKEN}/voice/file_1.oga").mock(
        return_value=httpx.Response(200, content=b"OggS-data")
    )

    async with httpx.AsyncClient() as http:
        data = await _client(http).download_file("voice/file_1.oga", max_bytes=1000)

    assert data == b"OggS-data"
    assert route.called


@respx.mock
async def test_download_file_over_limit_raises() -> None:
    respx.get(f"{API}/file/bot{TOKEN}/voice/file_1.oga").mock(
        return_value=httpx.Response(200, content=b"x" * 100)
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(FileTooLarge):
            await _client(http).download_file("voice/file_1.oga", max_bytes=10)


async def test_download_file_deadline_raises_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Медленный поток: общий дедлайн прерывает скачивание; ошибка без URL и токена (S5).
    monkeypatch.setattr(telegram_client, "DOWNLOAD_TIMEOUT_SEC", 0.05)

    async def slow_body() -> AsyncIterator[bytes]:
        yield b"part"
        await asyncio.sleep(5)
        yield b"rest"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=slow_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramError) as info:
            await _client(http).download_file("voice/file_1.oga", max_bytes=1000)

    assert info.value.description == "download timeout"
    assert TOKEN not in str(info.value)
    assert API not in str(info.value)


@pytest.mark.parametrize("file_path", ["../secret.txt", "/etc/passwd", "voice/../../x"])
@respx.mock
async def test_download_file_rejects_path_traversal(file_path: str) -> None:
    async with httpx.AsyncClient() as http:
        with pytest.raises(TelegramError) as info:
            await _client(http).download_file(file_path, max_bytes=1000)

    assert info.value.description == "invalid file path"


@respx.mock
async def test_set_webhook_sends_secret_and_allowed_updates() -> None:
    route = respx.post(f"{BOT_URL}/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )

    async with httpx.AsyncClient() as http:
        await _client(http).set_webhook(
            "https://harness.example.com/telegram/webhook",
            secret_token="test-webhook-secret-0123456789abcdef",
            allowed_updates=("message", "callback_query"),
        )

    assert json.loads(route.calls.last.request.content) == {
        "url": "https://harness.example.com/telegram/webhook",
        "secret_token": "test-webhook-secret-0123456789abcdef",
        "allowed_updates": ["message", "callback_query"],
    }


PROXY = "https://tg-proxy.example.com"


@respx.mock
async def test_custom_base_url_is_used_for_api_and_file_calls() -> None:
    api_route = respx.post(f"{PROXY}/bot{TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 5}})
    )
    file_route = respx.get(f"{PROXY}/file/bot{TOKEN}/voice/file_1.oga").mock(
        return_value=httpx.Response(200, content=b"OggS")
    )

    async with httpx.AsyncClient() as http:
        client = HttpxTelegramClient(TOKEN, http, base_url=PROXY)
        message_id = await client.send_message(CHAT_ID, "текст")
        data = await client.download_file("voice/file_1.oga", max_bytes=1000)

    assert message_id == 5
    assert data == b"OggS"
    assert api_route.called
    assert file_route.called


@respx.mock
async def test_custom_base_url_error_contains_no_token_or_url() -> None:
    respx.post(f"{PROXY}/bot{TOKEN}/sendMessage").mock(
        side_effect=httpx.ConnectError(f"cannot connect to {PROXY}/bot{TOKEN}/sendMessage")
    )

    async with httpx.AsyncClient() as http:
        client = HttpxTelegramClient(TOKEN, http, base_url=PROXY)
        with pytest.raises(TelegramError) as info:
            await client.send_message(CHAT_ID, "текст")

    assert TOKEN not in str(info.value)
    assert PROXY not in str(info.value)
    assert TOKEN not in repr(info.value)
