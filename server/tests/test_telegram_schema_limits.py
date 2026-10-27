import json

import pytest

from telegram_helpers import WEBHOOK
from app.models import Task


@pytest.mark.parametrize("update", [
    {"update_id": True}, {"update_id": "1"},
    {"update_id": 1, "message": {"message_id": "2", "chat": {"id": 3}}},
    {"update_id": 1, "message": {"message_id": 2, "chat": {"id": 3},
                                   "voice": {"file_id": "x", "file_size": -1}}},
    {"update_id": 1, "message": {"message_id": 2, "chat": {"id": 3},
                                   "voice": {"file_id": ""}}},
    {"update_id": 1, "message": {"message_id": 2, "chat": {"id": 3},
                                   "voice": {"file_id": "x", "file_size": True}}},
    {"update_id": 1, "message": {"message_id": 2, "chat": {"id": 3},
                                   "voice": {"file_id": "x" * 257}}},
    {"update_id": 1, "message": {"message_id": 2, "chat": {"id": 3},
                                   "text": "x" * 4097}},
])
async def test_strict_update_schema_rejects_bad_types(telegram, update):
    assert (await telegram.post(update)).status_code == 422


@pytest.mark.parametrize("update", [
    {"update_id": 101, "message": {"message_id": 10, "date": 1700000000,
     "chat": {"id": -123456, "type": "private", "title": "ignored", "username": "room",
              "first_name": "Chat", "extra_bot_field": True},
     "from": {"id": 42, "is_bot": False, "first_name": "Ada", "language_code": "ru"},
     "text": "Создай страницу", "entities": [{"offset": 0, "length": 5, "type": "bold"}]}},
    {"update_id": 102, "message": {"message_id": 11, "date": 1700000001,
     "chat": {"id": -123456, "type": "private"}, "from": {"id": 42, "is_bot": False},
     "voice": {"file_id": "voice-id", "file_unique_id": "unique-voice", "duration": 4,
               "mime_type": "audio/ogg", "file_size": 4096}}},
    {"update_id": 103, "message": {"message_id": 12, "date": 1700000002,
     "chat": {"id": -123456, "type": "private"}, "from": {"id": 42, "is_bot": False},
     "audio": {"file_id": "audio-id", "file_unique_id": "unique-audio", "duration": 8,
               "performer": "Ada", "title": "Note", "mime_type": "audio/mpeg", "file_size": 8192}}},
    {"update_id": 104, "callback_query": {"id": "callback", "from": {"id": 42, "is_bot": False},
     "chat_instance": "instance", "data": "pa" + "a" * 32,
     "message": {"message_id": 13, "date": 1700000003, "chat": {"id": -123456, "type": "private"}}}},
    {"update_id": 105, "message": {"message_id": 14, "date": 1700000004,
     "chat": {"id": -123456, "type": "private"}, "from": {"id": 42, "is_bot": False},
     "text": "Замечание", "reply_to_message": {"message_id": 13, "date": 1700000003,
     "chat": {"id": -123456, "type": "private"}, "from": {"id": 111, "is_bot": True},
     "text": "Ответьте на это сообщение с замечанием.", "entities": []}}},
])
async def test_full_bot_api_payload_shapes_are_accepted(telegram, update):
    assert (await telegram.post(update)).status_code == 200


async def test_caption_limit_is_enforced(telegram):
    update = telegram.message(media="audio")
    update["message"]["audio"]["caption"] = "x" * 4097
    assert (await telegram.post(update)).status_code == 422


async def test_webhook_stream_limit_returns_413_without_task(telegram, monkeypatch):
    from app.api.v1 import telegram as endpoint

    monkeypatch.setattr(endpoint, "MAX_WEBHOOK_BYTES", 24)
    body = json.dumps(telegram.message(text="x" * 100)).encode()

    async def streamed():
        yield body[:10]
        yield body[10:]

    response = await telegram.flow.client.post(WEBHOOK, content=streamed(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-test-secret"})
    assert response.status_code == 413
    assert telegram.flow.session.query(Task).count() == 0


async def test_oversized_content_length_is_rejected_before_body_read(telegram, monkeypatch):
    from app.api.v1 import telegram as endpoint

    monkeypatch.setattr(endpoint, "MAX_WEBHOOK_BYTES", 10)
    response = await telegram.flow.client.post(WEBHOOK, content=b"{}", headers={
        "X-Telegram-Bot-Api-Secret-Token": "webhook-test-secret", "Content-Length": "100"})
    assert response.status_code == 413
