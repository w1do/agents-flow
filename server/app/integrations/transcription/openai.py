from pathlib import Path
import json
from urllib.parse import urlsplit

from app.integrations import http
from app.integrations.transcription.base import TranscriptionError

MAX_RESPONSE_BYTES = 1024 * 1024


class OpenAITranscriber:
    def __init__(self, api_key, base_url, model):
        parsed = urlsplit(base_url)
        if parsed.scheme != "https":
            from app.integrations.transcription.base import ConfigurationError
            raise ConfigurationError("OPENAI_BASE_URL должен использовать HTTPS.")
        self._key, self._url, self._model = api_key, base_url.rstrip("/"), model

    async def transcribe(self, path: Path) -> str:
        try:
            async with http.client(timeout=60) as client:
                with path.open("rb") as audio:
                    async with client.stream("POST", self._url + "/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self._key}"},
                        data={"model": self._model}, files={"file": (path.name, audio)}) as response:
                        response.raise_for_status()
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                                raise ValueError()
                            data.extend(chunk)
                text = json.loads(data)["text"]
                if not isinstance(text, str) or not text.strip():
                    raise ValueError()
                return text.strip()
        except TranscriptionError:
            raise
        except Exception:
            raise TranscriptionError("Не удалось распознать аудио. Повторите или напишите текстом.") from None
