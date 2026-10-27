import asyncio

import pytest
from sqlalchemy import select

from app.models import IdempotencyKey, Task
from telegram_helpers import SECRET, WEBHOOK


async def test_admission_overflow_has_no_waiters_or_reservations(telegram, monkeypatch):
    from app.api.v1 import telegram as endpoint

    entered, resume = asyncio.Event(), asyncio.Event()
    runtime = telegram.runtime

    async def hold(*args):
        if len(runtime.updates.active) == 16:
            entered.set()
        await resume.wait()

    monkeypatch.setattr(endpoint, "handle", hold)
    active = [asyncio.create_task(telegram.post(telegram.message(text="Hold"))) for _ in range(16)]
    try:
        await asyncio.wait_for(entered.wait(), 2)
        responses = await asyncio.gather(*[telegram.post(telegram.message(text="Overflow"))
                                           for _ in range(32)])
        assert all(response.status_code == 503 for response in responses)
        assert len(runtime.updates.active) == 16
        assert not runtime.updates.done.items
    finally:
        resume.set()
        await asyncio.gather(*active)
    assert not runtime.updates.active
    assert (await telegram.post(telegram.message(text="Free"))).status_code == 200


async def test_evicted_update_replays_persisted_outcome_within_ttl(telegram):
    from app.integrations.telegram.dedup import scope
    from app.integrations.telegram.state import ExpiringCache

    update = telegram.message(text="Only one task")
    assert (await telegram.post(update)).status_code == 200
    session = telegram.flow.session
    row = session.scalar(select(IdempotencyKey).where(
        IdempotencyKey.scope == scope(telegram.runtime.settings)))
    assert row.idempotency_key == str(update["update_id"]) and row.response_body == {"ok": True}
    cache = telegram.runtime.updates.done
    # Exercise the exact default-size eviction, without waiting for TTL expiry.
    for number in range(10001, 20002):
        cache.put(number, True)
    assert cache.get(update["update_id"]) is None
    assert (await telegram.post(update)).status_code == 200
    telegram.runtime.updates.done = ExpiringCache(86400, 10000)  # process memory lost
    assert (await telegram.post(update)).status_code == 200
    assert session.query(Task).count() == 1


async def test_task_and_dedup_result_roll_back_together(telegram, monkeypatch):
    session = telegram.flow.session
    original = session.commit
    monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("DB offline")))
    update = telegram.message(text="Atomic task")
    assert (await telegram.post(update)).status_code == 503
    assert session.query(Task).count() == session.query(IdempotencyKey).count() == 0
    monkeypatch.setattr(session, "commit", original)
    assert (await telegram.post(update)).status_code == 200
    assert session.query(Task).count() == session.query(IdempotencyKey).count() == 1


@pytest.mark.parametrize("length", ["9" * 5000, "0" * 5000 + "1048577"])
async def test_huge_content_length_returns_413_before_reading(telegram, length):
    async def unread():
        raise AssertionError("Body must not be consumed")
        yield b""

    response = await telegram.flow.client.post(WEBHOOK, content=unread(), headers={
        "X-Telegram-Bot-Api-Secret-Token": SECRET, "Content-Length": length})
    assert response.status_code == 413


async def test_evicted_update_replay_does_not_extend_original_ttl(telegram, monkeypatch):
    from datetime import timedelta
    from app.core import time
    from app.integrations.telegram import state

    timestamp, ticks = time.now(), state.monotonic()
    update = telegram.message(text="Fixed TTL")
    assert (await telegram.post(update)).status_code == 200
    telegram.runtime.updates.done.items.clear()
    monkeypatch.setattr(time, "now", lambda: timestamp + timedelta(hours=23))
    monkeypatch.setattr(state, "monotonic", lambda: ticks + 23 * 3600)
    assert (await telegram.post(update)).status_code == 200
    monkeypatch.setattr(time, "now", lambda: timestamp + timedelta(hours=24, seconds=1))
    monkeypatch.setattr(state, "monotonic", lambda: ticks + 24 * 3600 + 1)
    assert (await telegram.post(update)).status_code == 200
    assert telegram.flow.session.query(Task).count() == 2
