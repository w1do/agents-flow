import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from app.integrations.telegram import client
from app.integrations.telegram.client import BotClient, TelegramError


class FakeClock:
    def __init__(self):
        self.now, self.deadlines = 0.0, []

    @asynccontextmanager
    async def timeout(self, delay):
        deadline = self.now + delay
        self.deadlines.append(deadline)
        try:
            yield
            if self.now >= deadline:
                raise TimeoutError
        finally:
            self.deadlines.pop()

    def advance(self, delay):
        self.now += delay
        if self.deadlines and self.now >= min(self.deadlines):
            raise TimeoutError


class Dripping(httpx.AsyncByteStream):
    def __init__(self, clock):
        self.closed, self.chunks, self.clock = False, 0, clock

    async def __aiter__(self):
        for _ in range(100):
            self.clock.advance(0.01)  # Each read completes before the per-read timeout.
            self.chunks += 1
            yield b" "

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("operation", ["send", "answer", "download"])
async def test_bot_operation_deadline_stops_dripping_response(monkeypatch, tmp_path, operation):
    clock = FakeClock()
    stream = Dripping(clock)

    async def handler(request):
        if request.url.path.endswith("getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "voice/file.ogg"}})
        return httpx.Response(200, stream=stream)

    original = httpx.AsyncClient
    monkeypatch.setattr(client, "timeout", clock.timeout)
    monkeypatch.setattr(client, "OPERATION_TIMEOUT", 0.04)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    bot = BotClient("safe-test-token")
    with pytest.raises(TelegramError):
        async with asyncio.timeout(1):
            if operation == "send":
                await bot.send_message("1", "notice")
            elif operation == "answer":
                await bot.answer_callback("q", "answer")
            else:
                await bot.download("id", tmp_path / "audio.ogg")
    assert 0 < stream.chunks < 100 and stream.closed


@pytest.mark.parametrize("operation", ["send", "answer"])
async def test_runtime_delivery_deadline_includes_custom_bot(telegram, monkeypatch, operation):
    from app.integrations.telegram import runtime

    cancelled = asyncio.Event()

    async def stalled(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(runtime, "DELIVERY_TIMEOUT", 0.01)
    monkeypatch.setattr(telegram.fake, "send_message", stalled)
    monkeypatch.setattr(telegram.fake, "answer_callback", stalled)
    async with asyncio.timeout(1):
        if operation == "send":
            assert await telegram.runtime.send("1", "notice") is None
        else:
            assert await telegram.runtime.answer("q", "answer") is None
    assert cancelled.is_set()
