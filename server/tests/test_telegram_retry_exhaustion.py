import asyncio

import pytest

from app.integrations.telegram.client import TelegramError
from app.services import telegram_delivery as delivery


@pytest.mark.parametrize("scope", ["chat", "bot"])
@pytest.mark.parametrize("empty_lane", [False, True])
async def test_fourth_429_delays_next_notice(telegram, monkeypatch, scope, empty_lane):
    now, calls = [0.0], []
    monkeypatch.setattr(delivery, "monotonic", lambda: now[0])

    async def sleep(delay):
        now[0] += delay

    async def send(chat, text, markup):
        calls.append((chat, text, now[0]))
        if text == "exhausted":
            return TelegramError("limited", retry_after=10, retry_scope=scope)
        return {"message_id": 1}

    monkeypatch.setattr(delivery, "sleep", sleep)
    monkeypatch.setattr(telegram.runtime, "send", send)
    queue = telegram.runtime.notifications
    queue.put_nowait(("A", "exhausted", None))
    if empty_lane:
        await asyncio.wait_for(queue.join(), 2)
    queue.put_nowait(("A" if scope == "chat" else "B", "next", None))
    await asyncio.wait_for(queue.join(), 2)
    assert [timestamp for _, text, timestamp in calls if text == "exhausted"] == [0, 10, 20, 30]
    assert calls[-1][1] == "next" and calls[-1][2] >= 40
