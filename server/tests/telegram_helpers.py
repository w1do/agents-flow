import asyncio
from itertools import count

import httpx
import pytest

from app.integrations.telegram.formatting import ACTION_CODES, keyboard

CHAT, USER = "-123456", 42
WEBHOOK = "/api/v1/telegram/webhook"
SECRET = "webhook-test-secret"


class FakeBot:
    def __init__(self):
        self.messages, self.answers, self.paths = [], [], []
        self.send_error = self.download_error = None

    async def send_message(self, chat, text, reply_markup=None):
        if self.send_error:
            raise self.send_error
        result = {"message_id": len(self.messages) + 100, "chat": chat,
                  "text": text, "reply_markup": reply_markup}
        self.messages.append(result)
        return result

    async def answer_callback(self, query, text):
        self.answers.append((query, text))

    async def download(self, file_id, destination):
        self.paths.append(destination)
        destination.write_bytes(b"fake audio")
        if self.download_error:
            raise self.download_error


@pytest.fixture(autouse=True)
def telegram_disabled_by_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "")


@pytest.fixture
def telegram_config(monkeypatch):
    from app.integrations.telegram import client

    fake = FakeBot()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:bot-test-secret")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "stub")
    monkeypatch.setattr(client, "create_client", lambda settings: fake)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Network is forbidden in Telegram tests")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    return fake


class Telegram:
    def __init__(self, flow, app, fake):
        self.flow, self.app, self.fake = flow, app, fake
        self.runtime, self.ids = app.state.telegram, count(1)

    async def drain(self):
        await asyncio.sleep(0)  # allow thread-safe post-commit enqueue callbacks
        await self.runtime.notifications.join()

    async def post(self, body, *, secret=SECRET):
        response = await self.flow.client.post(WEBHOOK, json=body,
                                              headers={"X-Telegram-Bot-Api-Secret-Token": secret})
        await self.drain()
        return response

    def message(self, *, text=None, media=None, chat=CHAT, user=USER, reply=None):
        message = {"message_id": 1000, "chat": {"id": int(chat)}, "from": {"id": user}}
        if text is not None:
            message["text"] = text
        if media:
            message[media] = {"file_id": "file-id", "file_name": "audio.mp3"}
        if reply is not None:
            from app.integrations.telegram.buttons import FEEDBACK_PROMPT

            message["reply_to_message"] = {"message_id": reply, "text": FEEDBACK_PROMPT,
                                           "from": {"id": 111, "is_bot": True}}
        return {"update_id": next(self.ids), "message": message}

    def callback(self, task, kind, decision, *, chat=CHAT, user=USER):
        from sqlalchemy import select
        from app.models import TaskEvent

        event_type = "plan" if kind == "plan" else "result"
        revision = self.flow.session.scalar(select(TaskEvent.id).where(
            TaskEvent.task_id == task.id, TaskEvent.event_type == event_type
        ).order_by(TaskEvent.created_at.desc()).limit(1))
        if revision is None:
            from app.repositories.task_history import TaskHistory

            revision = TaskHistory(self.flow.session).append(task.id, event_type, "Fixture revision").id
            self.flow.session.commit()
        rows = keyboard(kind, task.id, revision)["inline_keyboard"]
        data = next(row[0]["callback_data"] for row in rows
                    if row[0]["callback_data"][1] == ACTION_CODES[decision])
        return {"update_id": next(self.ids), "callback_query": {
            "id": "query-id", "from": {"id": user}, "data": data,
            "message": {"message_id": 1000, "chat": {"id": int(chat)}},
        }}


@pytest.fixture
async def telegram(telegram_config, flow, app):
    flow.project.telegram_chat_id = CHAT
    flow.session.commit()
    yield Telegram(flow, app, telegram_config)
