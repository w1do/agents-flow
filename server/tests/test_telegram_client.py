import logging
import asyncio

import httpx
import pytest

from app.integrations.telegram.client import BotClient, TelegramError


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    mock = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=mock, **kwargs))


async def test_bot_adapter_send_callback_and_file_download(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "voice/file.ogg"}})
        if request.method == "GET":
            return httpx.Response(200, content=b"voice bytes")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 123}})

    transport(monkeypatch, handle)
    bot = BotClient("123456:private-bot-token")
    assert (await bot.send_message("-1", "Message"))["message_id"] == 123
    await bot.answer_callback("query", "Saved")
    path = tmp_path / "audio.ogg"
    await bot.download("file-id", path)
    assert path.read_bytes() == b"voice bytes"
    assert calls[0].url.path.endswith("/sendMessage")
    assert calls[1].url.path.endswith("/answerCallbackQuery")
    assert calls[3].url.path.endswith("/voice/file.ogg")
    assert "private-bot-token" not in caplog.text


@pytest.mark.parametrize("code,body", [(200, {"ok": False, "description": "private-bot-token"}),
                                     (403, {"error": "private-bot-token"}), (200, {})])
async def test_bot_errors_are_safe(monkeypatch, code, body):
    transport(monkeypatch, lambda request: httpx.Response(code, json=body))
    with pytest.raises(TelegramError) as error:
        await BotClient("private-bot-token").send_message("-1", "Message")
    assert "private-bot-token" not in str(error.value) and "Traceback" not in str(error.value)


async def test_download_has_streaming_size_limit(monkeypatch, tmp_path):
    from app.integrations.telegram import client

    monkeypatch.setattr(client, "MAX_AUDIO_BYTES", 16)

    def handle(request):
        if request.method == "POST":
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "audio/file.mp3"}})
        return httpx.Response(200, content=b"x" * 17)

    transport(monkeypatch, handle)
    with pytest.raises(TelegramError, match="20 МБ"):
        await BotClient("private-token").download("file-id", tmp_path / "audio.mp3")


@pytest.mark.parametrize("path", ["../file", "https://foreign.test/file", "/file", "file?token=secret"])
async def test_download_rejects_unsafe_paths(monkeypatch, tmp_path, path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"file_path": path}})

    transport(monkeypatch, handle)
    with pytest.raises(TelegramError):
        await BotClient("private-token").download("file-id", tmp_path / "audio.mp3")
    assert len(calls) == 1


async def test_rate_limit_preserves_bot_api_delay(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 3}})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    transport(monkeypatch, handle)
    with pytest.raises(TelegramError) as error:
        await BotClient("safe-test-token").send_message("-1", "notice")
    assert error.value.retry_after == 3 and len(calls) == 1
