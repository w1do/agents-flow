"""Контрактные тесты STT-клиента (respx). Ключ и ответы провайдера в тестах не настоящие."""

import httpx
import pytest
import respx
from harness_server.adapters.stt import OpenAiCompatibleStt, SttError

pytestmark = pytest.mark.asyncio

API_URL = "https://polza.example.com/v1"
STT_KEY = "stt-key-0123456789abcdef"
ENDPOINT = f"{API_URL}/audio/transcriptions"
AUDIO = b"OggS-audio-bytes"


def _stt(http: httpx.AsyncClient) -> OpenAiCompatibleStt:
    return OpenAiCompatibleStt(API_URL, STT_KEY, "whisper-1", http)


@respx.mock
async def test_transcribe_sends_multipart() -> None:
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json={"text": "создай страницу"})
    )

    async with httpx.AsyncClient() as http:
        await _stt(http).transcribe(AUDIO, filename="voice.ogg", mime_type="audio/ogg")

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {STT_KEY}"
    assert b'name="model"\r\n\r\nwhisper-1' in request.content
    assert b'name="response_format"\r\n\r\njson' in request.content
    assert b'filename="voice.ogg"' in request.content
    assert b"Content-Type: audio/ogg" in request.content
    assert AUDIO in request.content


@respx.mock
async def test_transcribe_url_handles_trailing_slash() -> None:
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"text": "текст"}))

    async with httpx.AsyncClient() as http:
        stt = OpenAiCompatibleStt(f"{API_URL}/", STT_KEY, "whisper-1", http)
        await stt.transcribe(AUDIO, filename="voice.ogg", mime_type="audio/ogg")

    assert route.called


@respx.mock
async def test_transcribe_returns_stripped_text() -> None:
    respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json={"text": "  создай страницу контактов \n"})
    )

    async with httpx.AsyncClient() as http:
        text = await _stt(http).transcribe(AUDIO, filename="voice.ogg", mime_type="audio/ogg")

    assert text == "создай страницу контактов"


@respx.mock
async def test_transcribe_empty_text_raises() -> None:
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"text": "   "}))

    async with httpx.AsyncClient() as http:
        with pytest.raises(SttError, match="empty"):
            await _stt(http).transcribe(AUDIO, filename="voice.ogg", mime_type="audio/ogg")


@respx.mock
async def test_transcribe_http_error_raises_without_key() -> None:
    respx.post(ENDPOINT).mock(return_value=httpx.Response(500, json={"error": "upstream failed"}))

    async with httpx.AsyncClient() as http:
        stt = _stt(http)
        with pytest.raises(SttError) as info:
            await stt.transcribe(AUDIO, filename="voice.ogg", mime_type="audio/ogg")

    assert "stt http 500" in str(info.value)
    assert STT_KEY not in str(info.value)
    assert STT_KEY not in repr(info.value)
    assert STT_KEY not in repr(stt)


@respx.mock
async def test_transcribe_timeout_raises() -> None:
    respx.post(ENDPOINT).mock(side_effect=httpx.ReadTimeout("read timed out"))

    async with httpx.AsyncClient() as http:
        with pytest.raises(SttError) as info:
            await _stt(http).transcribe(AUDIO, filename="voice.ogg", mime_type="audio/ogg")

    assert "ReadTimeout" in str(info.value)
    assert STT_KEY not in str(info.value)


@respx.mock
async def test_transcribe_invalid_json_raises() -> None:
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, content=b"<html>not json"))

    async with httpx.AsyncClient() as http:
        with pytest.raises(SttError, match="invalid response"):
            await _stt(http).transcribe(AUDIO, filename="voice.ogg", mime_type="audio/ogg")
