import asyncio

import pytest

from app.models import TaskEvent
from telegram_helpers import CHAT, USER
from app.integrations.telegram.buttons import FEEDBACK_PROMPT


@pytest.mark.parametrize("failure", ["cancel", "exception", "invalid", "commit"])
async def test_prompt_failure_releases_reservation_and_retries_same_update(telegram, monkeypatch, failure):
    task = telegram.flow.task("backlog")
    update = telegram.callback(task, "plan", "rejected")
    await telegram.drain()
    original = telegram.fake.send_message
    original_commit = telegram.flow.session.commit

    async def broken(*args, **kwargs):
        assert not telegram.flow.session.in_transaction()
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "invalid":
            return None
        if failure == "exception":
            raise RuntimeError("offline")
        return await original(*args, **kwargs)

    monkeypatch.setattr(telegram.fake, "send_message", broken)
    if failure == "commit":
        def offline():
            raise RuntimeError("DB offline")
        monkeypatch.setattr(telegram.flow.session, "commit", offline)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await telegram.post(update)
    else:
        assert (await telegram.post(update)).status_code == 503
    assert not telegram.runtime.feedback.items
    assert not telegram.runtime.actions.cache.items
    assert not telegram.runtime.updates.active
    assert telegram.runtime.updates.done.get(update["update_id"]) is None
    monkeypatch.setattr(telegram.fake, "send_message", original)
    monkeypatch.setattr(telegram.flow.session, "commit", original_commit)
    assert (await telegram.post(update)).status_code == 200
    prompt = telegram.fake.messages[-1]
    assert prompt["text"] == FEEDBACK_PROMPT
    assert telegram.runtime.feedback.get(CHAT, USER, prompt["message_id"]) is not None
    assert (await telegram.post(update)).status_code == 200
    assert telegram.fake.messages[-1] is prompt


async def test_feedback_database_failure_keeps_pending_reply_for_retry(telegram, monkeypatch):
    task = telegram.flow.task("backlog")
    await telegram.post(telegram.callback(task, "plan", "rejected"))
    prompt = next(row["message_id"] for row in telegram.fake.messages if row["text"] == FEEDBACK_PROMPT)
    reply = telegram.message(text="Keep all feedback", reply=prompt)
    original = telegram.flow.session.commit

    def failed_commit():
        telegram.flow.session.flush()  # changes really reached the transaction
        raise RuntimeError("DB commit failed")

    monkeypatch.setattr(telegram.flow.session, "commit", failed_commit)
    assert (await telegram.post(reply)).status_code == 503
    assert telegram.runtime.feedback.get(CHAT, USER, prompt) is not None
    telegram.flow.session.refresh(task)
    assert task.status == "backlog"
    assert telegram.flow.session.query(TaskEvent).filter_by(event_type="plan_decision").count() == 0
    monkeypatch.setattr(telegram.flow.session, "commit", original)
    assert (await telegram.post(reply)).status_code == 200
    assert telegram.runtime.feedback.get(CHAT, USER, prompt) is None
    assert (await telegram.post(reply)).status_code == 200
    event = telegram.flow.session.query(TaskEvent).filter_by(event_type="plan_decision").one()
    assert event.payload["feedback"] == "Keep all feedback"
