import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations import http
from app.integrations.transcription import create_transcriber
from app.integrations.transcription.base import ConfigurationError, TranscriptionError


def settings(**values):
    return Settings(_env_file=None, database_url="sqlite://", jwt_secret="x" * 32, **values)


async def test_stub_returns_text_without_network(tmp_path):
    provider = create_transcriber(settings())
    assert await provider.transcribe(tmp_path / "audio.ogg") == "Тестовая голосовая задача"


def test_unknown_provider_is_safe_configuration_error():
    with pytest.raises(ConfigurationError, match="TRANSCRIPTION_PROVIDER") as error:
        create_transcriber(settings(transcription_provider="secret-provider-value"))
    assert "secret-provider-value" not in str(error.value)


def test_openai_without_key_is_configuration_error():
    with pytest.raises(ConfigurationError, match="TRANSCRIPTION_API_KEY"):
        create_transcriber(settings(transcription_provider="openai"))


@pytest.mark.parametrize("url", ["http://provider.example/v1", "http://localhost/v1", "http://127.0.0.1/v1"])
def test_http_transcription_url_is_rejected(url):
    with pytest.raises(ConfigurationError, match="HTTPS"):
        create_transcriber(settings(transcription_provider="openai", openai_api_key="private-key",
                                   openai_base_url=url))


async def test_openai_uses_multipart_and_configured_endpoint(tmp_path, monkeypatch):
    path = tmp_path / "recording.ogg"
    path.write_bytes(b"voice-data")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"text": "  Распознанная задача  "})

    monkeypatch.setattr(http, "client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    provider = create_transcriber(settings(transcription_provider="openai",
                                         transcription_api_key=SecretStr("private-api-key"),
                                         openai_base_url="https://provider.test/v1/"))
    assert await provider.transcribe(path) == "Распознанная задача"
    request = requests[0]
    assert str(request.url) == "https://provider.test/v1/audio/transcriptions"
    assert request.headers["Authorization"] == "Bearer private-api-key"
    assert "multipart/form-data" in request.headers["Content-Type"]
    assert all(value in request.content for value in (b"recording.ogg", b"voice-data", b"whisper-1"))


@pytest.mark.parametrize("code,body", [(401, {"error": "secret-key"}), (200, {}), (200, {"text": ""})])
async def test_openai_errors_are_compact(tmp_path, monkeypatch, code, body):
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"audio")
    transport = httpx.MockTransport(lambda request: httpx.Response(code, json=body))
    monkeypatch.setattr(http, "client", lambda **kw: httpx.AsyncClient(transport=transport))
    provider = create_transcriber(settings(transcription_provider="openai", openai_api_key="secret-key"))
    with pytest.raises(TranscriptionError) as error:
        await provider.transcribe(path)
    assert "secret-key" not in str(error.value) and "Traceback" not in str(error.value)


async def test_openai_response_is_byte_limited_and_text_is_preserved(tmp_path, monkeypatch):
    from app.integrations.transcription import openai

    path = tmp_path / "audio.mp3"
    path.write_bytes(b"audio")
    monkeypatch.setattr(openai, "MAX_RESPONSE_BYTES", 1024)
    text = "x" * 300
    monkeypatch.setattr(http, "client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"text": text}))))
    provider = create_transcriber(settings(transcription_provider="openai", openai_api_key="private-key",
                                           openai_base_url="https://provider.test/v1"))
    assert await provider.transcribe(path) == text


async def test_openai_oversized_response_is_rejected_without_key_leak(tmp_path, monkeypatch):
    from app.integrations.transcription import openai

    path = tmp_path / "audio.mp3"
    path.write_bytes(b"audio")
    monkeypatch.setattr(openai, "MAX_RESPONSE_BYTES", 64)
    monkeypatch.setattr(http, "client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"text": "x" * 300}))))
    provider = create_transcriber(settings(transcription_provider="openai", openai_api_key="private-key"))
    with pytest.raises(TranscriptionError) as error:
        await provider.transcribe(path)
    assert "private-key" not in str(error.value)
