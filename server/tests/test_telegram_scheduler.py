import asyncio

import pytest

from app.integrations.telegram.client import TelegramError


@pytest.fixture
def delivery():
    from app.services import telegram_delivery

    return telegram_delivery


async def test_delayed_chat_does_not_block_other_chat_or_reorder_its_messages(telegram, monkeypatch, delivery):
    sleeping, release, other = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls, attempts = [], 0
    now = [10.0]
    monkeypatch.setattr(delivery, "monotonic", lambda: now[0])

    async def sleep(delay):
        sleeping.set()
        await release.wait()
        now[0] += delay

    async def send(chat, text, markup):
        nonlocal attempts
        calls.append((chat, text, now[0]))
        if chat == "A":
            attempts += 1
            if attempts == 1:
                return TelegramError("limited", retry_after=300)
        else:
            other.set()
        return {"message_id": 1}

    monkeypatch.setattr(delivery, "sleep", sleep)
    monkeypatch.setattr(telegram.runtime, "send", send)
    queue = telegram.runtime.notifications
    queue.put_nowait(("A", "first", None))
    await asyncio.wait_for(sleeping.wait(), 2)
    queue.put_nowait(("A", "second", None))
    queue.put_nowait(("B", "independent", None))
    try:
        await asyncio.wait_for(other.wait(), 2)
        assert calls == [("A", "first", 10), ("B", "independent", 10)]
    finally:
        release.set()
    await telegram.drain()
    assert [(chat, text) for chat, text, _ in calls] == [
        ("A", "first"), ("B", "independent"), ("A", "first"), ("A", "second")]
    assert calls[2][2] >= 310


@pytest.mark.parametrize("scope", ["chat", "bot"])
async def test_retry_scope_and_backoff_without_retry_after(telegram, monkeypatch, scope, delivery):
    now, calls = [100.0], []
    monkeypatch.setattr(delivery, "monotonic", lambda: now[0])

    async def sleep(delay):
        now[0] += delay

    async def send(chat, *args):
        calls.append((chat, now[0]))
        return TelegramError("temporary") if len(calls) < 4 else {"message_id": 1}

    monkeypatch.setattr(delivery, "sleep", sleep)
    monkeypatch.setattr(telegram.runtime, "send", send)
    scheduler = delivery.Scheduler(telegram.runtime)
    scheduler.blocked[None if scope == "bot" else "B"] = 105
    await scheduler.deliver(("A", "notice", None))
    assert [timestamp - calls[0][1] for _, timestamp in calls] == [0, 0.25, 0.75, 1.75]
    assert calls[0][1] == (105 if scope == "bot" else 100)


async def test_bot_scoped_retry_delays_other_chats(telegram, monkeypatch, delivery):
    now = [0.0]
    calls = []
    monkeypatch.setattr(delivery, "monotonic", lambda: now[0])

    async def sleep(delay):
        now[0] += delay

    async def send(chat, *args):
        calls.append((chat, now[0]))
        if len(calls) == 1:
            return TelegramError("global", retry_after=500, retry_scope="bot")
        return {"message_id": 1}

    monkeypatch.setattr(delivery, "sleep", sleep)
    monkeypatch.setattr(telegram.runtime, "send", send)
    scheduler = delivery.Scheduler(telegram.runtime)
    await scheduler.deliver(("A", "notice", None))
    await scheduler.deliver(("B", "notice", None))
    assert calls == [("A", 0), ("A", 500), ("B", 500)]


async def test_scheduled_notices_are_included_in_queue_bound(delivery):
    queue = delivery.DeliveryQueue(maxsize=2)
    queue.put_nowait(("A", "1", None))
    queue.put_nowait(("A", "2", None))
    await queue.get()  # moved from queue to delayed delivery
    with pytest.raises(asyncio.QueueFull):
        queue.put_nowait(("B", "3", None))
    queue.task_done("A")
    queue.put_nowait(("B", "3", None))


async def test_delivery_attempt_has_total_deadline(telegram, monkeypatch, delivery):
    attempts = []
    monkeypatch.setattr(delivery, "ATTEMPT_TIMEOUT", 0.01)

    async def sleep(delay):
        pass

    async def send(*args):
        attempts.append(1)
        await asyncio.Event().wait()

    monkeypatch.setattr(delivery, "sleep", sleep)
    # A no-op sleep needs a clock that advances past each scheduled delay.
    ticks = iter(range(100))
    monkeypatch.setattr(delivery, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(telegram.runtime, "send", send)
    await asyncio.wait_for(delivery.Scheduler(telegram.runtime).deliver(("A", "notice", None)), 1)
    assert len(attempts) == 4
