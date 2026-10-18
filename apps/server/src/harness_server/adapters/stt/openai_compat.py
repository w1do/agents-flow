"""STT через OpenAI-совместимый протокол: POST <api_url>/audio/transcriptions (D-05)."""

import httpx

from harness_server.adapters.stt.protocol import SttError

# Подключение короче чтения: недоступный провайдер должен отвечать быстро.
_CONNECT_TIMEOUT_SEC = 10.0


class OpenAiCompatibleStt:
    """OpenAI-совместимый POST <api_url>/audio/transcriptions (D-05).

    Ключ передаётся только заголовком Authorization. Язык провайдер определяет сам.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        http: httpx.AsyncClient,
        *,
        timeout_sec: float = 120.0,
    ) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._model = model
        self._http = http
        self._timeout_sec = timeout_sec

    def __repr__(self) -> str:
        # Ключ в repr не выводим.
        return f"OpenAiCompatibleStt(model={self._model})"

    async def transcribe(self, audio: bytes, *, filename: str, mime_type: str) -> str:
        """Отправляет файл как есть и возвращает текст без пробелов по краям.

        Ошибки — только SttError: текст исключения httpx может содержать URL и заголовки запроса.
        """
        url = self._api_url.rstrip("/") + "/audio/transcriptions"
        try:
            response = await self._http.post(
                url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                data={"model": self._model, "response_format": "json"},
                files={"file": (filename, audio, mime_type)},
                timeout=httpx.Timeout(self._timeout_sec, connect=_CONNECT_TIMEOUT_SEC),
            )
        except httpx.HTTPError as exc:
            raise SttError(f"stt request failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise SttError(f"stt http {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise SttError("stt invalid response") from None
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise SttError("stt invalid response")
        stripped = text.strip()
        if not stripped:
            raise SttError("stt empty transcription")
        return stripped
