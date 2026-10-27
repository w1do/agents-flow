import asyncio

import pytest
from sqlalchemy import func, select

from app.models import Task
from app.integrations.telegram.client import TelegramError
from telegram_helpers import WEBHOOK, SECRET


async def test_concurrent_delivery_cannot_duplicate_task(telegram, monkeypatch):
    entered, resume = asyncio.Event(), asyncio.Event()
    original = telegram.fake.download

    async def delayed(*args):
        entered.set()
        await resume.wait()
        await original(*args)

    monkeypatch.setattr(telegram.fake, "download", delayed)
    update = telegram.message(media="voice")
    first = asyncio.create_task(telegram.post(update))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        second = await telegram.post(update)
        assert second.status_code == 503
    finally:
        resume.set()
    assert (await first).status_code == 200
    assert telegram.flow.session.scalar(select(func.count()).select_from(Task)) == 1


async def test_update_dedup_expires(telegram, monkeypatch):
    from datetime import timedelta
    from app.core import time
    from app.integrations.telegram import state

    update = telegram.message(text="Repeat after TTL")
    assert (await telegram.post(update)).status_code == 200
    now = state.monotonic()
    timestamp = time.now()
    monkeypatch.setattr(state, "monotonic", lambda: now + 86401)
    monkeypatch.setattr(time, "now", lambda: timestamp + timedelta(seconds=86401))
    assert (await telegram.post(update)).status_code == 200
    assert telegram.flow.session.scalar(select(func.count()).select_from(Task)) == 2


async def test_cancellation_after_decision_commit_does_not_repeat_it(telegram, monkeypatch):
    task = telegram.flow.task("ready", leased=True)
    update = telegram.callback(task, "result", "keep_ready")
    original = telegram.fake.answer_callback

    async def cancelled(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(telegram.fake, "answer_callback", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await telegram.post(update)
    monkeypatch.setattr(telegram.fake, "answer_callback", original)
    assert (await telegram.post(update)).status_code == 200
    card = (await telegram.flow.send("GET", f"/tasks/{task.id}")).json()
    assert len([event for event in card["events"] if event["event_type"] == "result_decision"]) == 1


async def test_ambiguous_chat_binding_is_ignored(telegram):
    from app.repositories.project import ProjectRepository
    from telegram_helpers import CHAT

    ProjectRepository(telegram.flow.session).create(name="Duplicate", telegram_chat_id=CHAT)
    telegram.flow.session.commit()
    assert (await telegram.post(telegram.message(text="Ignore ambiguous routing"))).status_code == 200
    assert telegram.flow.session.scalar(select(func.count()).select_from(Task)) == 0


async def test_authorization_checked_before_parsing_body(telegram):
    response = await telegram.flow.client.post(WEBHOOK, content="INVALID JSON")
    assert response.status_code == 401
    response = await telegram.flow.client.post(WEBHOOK, content="INVALID JSON",
                                               headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
    assert response.status_code == 422 and "INVALID JSON" not in response.text


@pytest.mark.parametrize("retry_after", [30, 121, 3600])
async def test_notification_retries_after_long_retry_after(telegram, monkeypatch, retry_after):
    from app.services import telegram_delivery as notification_events

    now, attempts = [100.0], []
    monkeypatch.setattr(notification_events, "monotonic", lambda: now[0])

    async def fake_sleep(delay):
        now[0] += delay

    async def send(*args):
        attempts.append(now[0])
        return TelegramError("rate limited", retry_after=retry_after) if len(attempts) == 1 else {"message_id": 1}

    monkeypatch.setattr(notification_events, "sleep", fake_sleep)
    monkeypatch.setattr(telegram.runtime, "send", send)
    task = telegram.flow.task("planning", leased=True)
    assert (await telegram.flow.report(task, "plan", {"plan_text": "Plan"})).status_code == 200
    await telegram.drain()
    assert len(attempts) == 2 and attempts[1] - attempts[0] == retry_after
