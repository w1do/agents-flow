import asyncio
from contextlib import asynccontextmanager

import pytest

from app.integrations.telegram import audio
from app.integrations.telegram.client import TelegramError
from app.integrations.telegram.state import ExpiringCache


def test_expiring_cache_is_bounded_and_prunes_expired(monkeypatch):
    from app.integrations.telegram import state

    now = 10
    monkeypatch.setattr(state, "monotonic", lambda: now)
    cache = ExpiringCache(5, 2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert len(cache.items) == 2 and cache.get("a") is None
    now += 6
    assert cache.get("b") is None and not cache.items


def test_short_ttl_expires_before_older_long_ttl(monkeypatch):
    from app.integrations.telegram import state

    now = 10
    monkeypatch.setattr(state, "monotonic", lambda: now)
    cache = ExpiringCache(86400, 4)
    cache.put("long", 1)
    cache.put("short", 2, ttl=900)
    now += 901
    assert cache.get("short") is None and cache.get("long") == 1


async def test_parallel_audio_is_rejected(telegram):
    telegram.runtime.audio_active = 2
    with pytest.raises(TelegramError, match="другие аудио"):
        await audio.transcribe(telegram.runtime, type("Media", (), {
            "file_size": 1, "file_name": "x.mp3", "file_id": "id"})())
    assert telegram.runtime.audio_active == 2


async def test_each_chat_has_one_audio_slot(telegram, monkeypatch, tmp_path):
    from app.integrations import transcription

    started, release = asyncio.Event(), asyncio.Event()

    class Slow:
        async def transcribe(self, path):
            started.set()
            await release.wait()
            return "done"

    monkeypatch.setattr(transcription, "create_transcriber", lambda _: Slow())
    media = type("Media", (), {"file_size": 1, "file_name": "x.mp3", "file_id": "id"})()
    first = asyncio.create_task(audio.transcribe(telegram.runtime, media, chat="one"))
    await started.wait()
    with pytest.raises(TelegramError):
        await audio.transcribe(telegram.runtime, media, chat="one")
    second = asyncio.create_task(audio.transcribe(telegram.runtime, media, chat="two"))
    await asyncio.sleep(0)
    assert telegram.runtime.audio_active == 2 and telegram.runtime.audio_chats == {"one", "two"}
    release.set()
    await asyncio.gather(first, second)


async def test_audio_timeout_removes_temp_file(telegram, monkeypatch, tmp_path):
    from pathlib import Path

    from app.integrations import transcription
    monkeypatch.setattr(transcription, "create_transcriber", lambda settings: type("Slow", (), {
        "transcribe": staticmethod(lambda path: asyncio.sleep(0))})())
    @asynccontextmanager
    async def expired(_):
        yield
        raise TimeoutError

    monkeypatch.setattr(audio, "timeout", expired)
    original = audio.NamedTemporaryFile
    paths = []

    def tracked(**kwargs):
        temporary = original(dir=tmp_path, **kwargs)
        paths.append(Path(temporary.name))
        return temporary

    monkeypatch.setattr(audio, "NamedTemporaryFile", tracked)
    media = type("Media", (), {"file_size": 1, "file_name": "x.mp3", "file_id": "id"})()
    with pytest.raises(TelegramError, match="слишком много времени"):
        await audio.transcribe(telegram.runtime, media)
    assert telegram.runtime.audio_active == 0
    assert paths and all(not path.exists() for path in paths)
