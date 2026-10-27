import asyncio
from contextlib import asynccontextmanager

from app.integrations.telegram.client import TelegramError
from app.repositories.project import ProjectRepository
from app.schemas.tasks import TaskCreate
from app.services import tasks, telegram_delivery as delivery
from telegram_helpers import CHAT


class DeadlineClock:
    """Advance only delivery deadlines, leaving the fixture/event-loop clock intact."""
    def __init__(self):
        self.now, self.deadlines, self.expired = 0, {}, set()

    @asynccontextmanager
    async def timeout(self, seconds):
        task = asyncio.current_task()
        self.deadlines[task] = self.now + seconds
        try:
            yield
        except asyncio.CancelledError:
            if task in self.expired:
                self.expired.remove(task)
                task.uncancel()
                raise TimeoutError from None
            raise
        finally:
            self.deadlines.pop(task, None)

    def advance(self, seconds):
        self.now += seconds
        for task, deadline in list(self.deadlines.items()):
            if deadline <= self.now:
                self.expired.add(task)
                task.cancel()


async def test_256_notices_from_delayed_chat_allow_other_chat(telegram, monkeypatch, caplog):
    now, calls = [0.0], []
    sleeping, resume, other_sent = asyncio.Event(), asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(delivery, "monotonic", lambda: now[0])

    async def sleep(delay):
        sleeping.set()
        await resume.wait()
        now[0] += delay

    async def send(chat, text, markup):
        calls.append(chat)
        if len(calls) == 1:
            return TelegramError("limited", retry_after=3600)
        if chat == "-999":
            other_sent.set()
        return {"message_id": 1}

    monkeypatch.setattr(delivery, "sleep", sleep)
    monkeypatch.setattr(telegram.runtime, "send", send)
    flow = telegram.flow
    other = ProjectRepository(flow.session).create(name="Other", telegram_chat_id="-999")
    body = TaskCreate(title="Notice", description="PRIVATE CONTENT",
                      source_type="api", source_text="PRIVATE CONTENT")
    for _ in range(256):
        tasks.create(flow.session, flow.project.id, body)
    flow.session.commit()
    await asyncio.wait_for(sleeping.wait(), 2)
    tasks.create(flow.session, other.id, body)
    flow.session.commit()
    try:
        await asyncio.wait_for(other_sent.wait(), 2)
        assert calls == [CHAT, "-999"]
        assert caplog.text.count("telegram_notification_chat_quota_full") == 240
        for private in (CHAT, "PRIVATE CONTENT", "webhook-test-secret", "123456:bot-test-secret"):
            assert private not in caplog.text
    finally:
        resume.set()
    await telegram.drain()
    assert calls.count(CHAT) == 17  # 16 admitted notices, including one retry
    # Finished deliveries release the chat quota for the next event.
    tasks.create(flow.session, flow.project.id, body)
    flow.session.commit()
    await telegram.drain()
    assert calls.count(CHAT) == 18


async def test_256_admitted_notices_wait_for_slots_without_losing_attempts(telegram, monkeypatch, caplog):
    clock = DeadlineClock()
    started, sent = asyncio.Queue(), []
    monkeypatch.setattr(delivery, "timeout", clock.timeout)

    async def send(chat, text, markup):
        release = asyncio.Event()
        sent.append((chat, text))
        started.put_nowait(release)
        await release.wait()
        return {"message_id": 1}

    monkeypatch.setattr(telegram.runtime, "send", send)
    queue = telegram.runtime.notifications
    expected = [(str(index), str(index)) for index in range(256)]
    for chat, text in expected:
        queue.put_nowait((chat, text, None))
    for _ in range(16):
        batch = [await asyncio.wait_for(started.get(), 2) for _ in range(16)]
        clock.advance(10)  # every send remains below its 30 s deadline
        for release in batch:
            release.set()
        await asyncio.sleep(0)
    await asyncio.wait_for(queue.join(), 2)
    assert sorted(sent) == sorted(expected)
    assert "telegram_notification_delivery_exhausted" not in caplog.text
