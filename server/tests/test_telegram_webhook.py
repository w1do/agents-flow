import asyncio

import pytest
from sqlalchemy import select

from app.integrations import transcription
from app.models import Task
from telegram_helpers import CHAT, WEBHOOK


def tasks(telegram):
    return list(telegram.flow.session.scalars(select(Task)))


@pytest.mark.parametrize("secret", ["", "wrong"])
async def test_secret_required(telegram, secret):
    response = await telegram.post(telegram.message(text="Private request"), secret=secret)
    assert response.status_code == 401 and tasks(telegram) == []
    assert telegram.fake.messages == []


async def test_foreign_chat_ignored_without_text_in_logs(telegram, caplog):
    caplog.set_level("INFO")
    response = await telegram.post(telegram.message(text="PRIVATE FOREIGN REQUEST", chat="98765"))
    assert response.status_code == 200 and tasks(telegram) == []
    assert telegram.fake.messages == [] and "PRIVATE FOREIGN REQUEST" not in caplog.text
    assert "telegram_chat_unbound_or_ambiguous" in caplog.text


async def test_text_creates_task_and_link_once(telegram):
    update = telegram.message(text="Создай страницу")
    assert (await telegram.post(update)).status_code == 200
    assert (await telegram.post(update)).status_code == 200
    task, = tasks(telegram)
    assert (task.status, task.source_type) == ("new", "telegram_text")
    assert task.description == task.source_text == "Создай страницу"
    notice, = telegram.fake.messages
    assert str(task.id) in notice["text"] and "/tasks/" in notice["text"]


@pytest.mark.parametrize("media", ["voice", "audio"])
async def test_audio_success_and_cleanup(telegram, media):
    assert (await telegram.post(telegram.message(media=media))).status_code == 200
    task, = tasks(telegram)
    assert task.source_type == "telegram_voice" and task.status == "new"
    assert task.source_text == task.description == "Тестовая голосовая задача"
    assert task.source_text in telegram.fake.messages[-1]["text"]
    assert telegram.fake.paths and all(not path.exists() for path in telegram.fake.paths)


@pytest.mark.parametrize("failure", ["provider", "download"])
async def test_audio_failure_and_cleanup(telegram, monkeypatch, caplog, failure):
    class FailingProvider:
        async def transcribe(self, path):
            assert path.exists()
            raise RuntimeError("PRIVATE PROVIDER KEY")

    if failure == "provider":
        monkeypatch.setattr(transcription, "create_transcriber", lambda _: FailingProvider())
    else:
        telegram.fake.download_error = RuntimeError("PRIVATE PROVIDER KEY")
    response = await telegram.post(telegram.message(media="voice"))
    assert response.status_code == 200 and tasks(telegram) == []
    assert telegram.fake.paths and all(not path.exists() for path in telegram.fake.paths)
    assert "напишите текстом" in telegram.fake.messages[-1]["text"]
    assert "PRIVATE PROVIDER KEY" not in response.text + caplog.text + str(telegram.fake.messages)


@pytest.mark.parametrize("stage", ["download", "provider"])
async def test_cancelled_audio_cleans_file_and_releases_reservation(telegram, monkeypatch, stage):
    update = telegram.message(media="audio")
    if stage == "download":
        telegram.fake.download_error = asyncio.CancelledError()
    else:
        class CancelledProvider:
            async def transcribe(self, path):
                raise asyncio.CancelledError()

        original = transcription.create_transcriber
        monkeypatch.setattr(transcription, "create_transcriber", lambda _: CancelledProvider())
    with pytest.raises(asyncio.CancelledError):
        await telegram.post(update)
    assert tasks(telegram) == [] and all(not path.exists() for path in telegram.fake.paths)
    telegram.fake.download_error = None
    if stage == "provider":
        monkeypatch.setattr(transcription, "create_transcriber", original)
    assert (await telegram.post(update)).status_code == 200
    assert len(tasks(telegram)) == 1


@pytest.mark.parametrize("provider", ["unknown-private-provider", "openai"])
async def test_misconfigured_provider_keeps_server_running(telegram, monkeypatch, provider):
    settings = telegram.runtime.settings
    monkeypatch.setattr(settings, "transcription_provider", provider)
    monkeypatch.setattr(settings, "transcription_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    assert (await telegram.post(telegram.message(media="voice"))).status_code == 200
    assert tasks(telegram) == [] and telegram.fake.paths == []
    assert "не настроена" in telegram.fake.messages[-1]["text"]
    assert "TRANSCRIPTION" not in telegram.fake.messages[-1]["text"]
    assert provider not in telegram.fake.messages[-1]["text"]
    assert (await telegram.flow.client.get("/healthz")).status_code == 200


async def test_malformed_update_and_missing_secret_config(telegram, monkeypatch):
    response = await telegram.post({"update_id": "PRIVATE INVALID VALUE"})
    assert response.status_code == 422 and "PRIVATE INVALID VALUE" not in response.text
    monkeypatch.setattr(telegram.runtime.settings, "telegram_webhook_secret", None)
    assert (await telegram.post(telegram.message(text="Hi"))).status_code == 401


async def test_oversized_audio_never_downloaded(telegram):
    update = telegram.message(media="audio")
    update["message"]["audio"]["file_size"] = 21 * 1024 * 1024
    assert (await telegram.post(update)).status_code == 200
    assert tasks(telegram) == [] and telegram.fake.paths == []


async def test_ordinary_text_reply_is_task_input(telegram):
    update = telegram.message(text="Use this as context", reply=123)
    update["message"]["reply_to_message"] = {"message_id": 123, "text": "Ordinary message",
                                            "from": {"id": 55}}
    assert (await telegram.post(update)).status_code == 200
    task, = tasks(telegram)
    assert task.source_text == "Use this as context" and task.source_type == "telegram_text"


async def test_full_transcription_is_saved_for_panel_and_clipped_only_in_notice(telegram, monkeypatch):
    from app.integrations.telegram import audio
    from app.integrations.telegram.formatting import MESSAGE_LIMIT, units

    text = "Распознанная задача " * 900

    async def transcribe(*args, **kwargs):
        return text

    monkeypatch.setattr(audio, "transcribe", transcribe)
    assert (await telegram.post(telegram.message(media="voice"))).status_code == 200
    task = tasks(telegram)[0]
    card = (await telegram.flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["source_text"] == text and card["description"] == text
    notice = telegram.fake.messages[-1]["text"]
    assert units(notice) <= MESSAGE_LIMIT and "полный текст — в панели" in notice


