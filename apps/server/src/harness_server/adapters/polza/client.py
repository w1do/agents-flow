"""Клиент Polza AI: OpenAI-совместимый chat completions с одной повторной попытки (D-31)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Final

import httpx

from harness_server.adapters.polza.protocol import RouterError, RouterReply

POLZA_API_URL: Final = "https://polza.ai/api/v1"
REQUEST_TIMEOUT_SEC: Final = 10.0  # жёсткий дедлайн одной попытки
CONNECT_TIMEOUT_SEC: Final = 5.0
RETRY_DELAY_SEC: Final = 1.0
MAX_RETRY_AFTER_SEC: Final = 5.0
MAX_TOKENS: Final = 300
_RETRY_STATUSES: Final = frozenset({408, 429, 500, 502, 503, 504})


class PolzaRouter:
    """OpenAI-совместимый POST <api_url>/chat/completions (D-31).

    httpx.AsyncClient принадлежит вызывающему.

    Ключ — только в заголовке Authorization. Не больше двух запросов на вызов complete.
    Исключения не содержат ключ, URL и текст ответа: только машинный reason.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        http: httpx.AsyncClient,
        *,
        timeout_sec: float = REQUEST_TIMEOUT_SEC,
        retry_delay_sec: float = RETRY_DELAY_SEC,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._model = model
        self._http = http
        self._timeout_sec = timeout_sec
        self._retry_delay_sec = retry_delay_sec
        self._sleep = sleep

    @property
    def api_url(self) -> str:
        """Базовый URL, как передан в конструктор."""
        return self._api_url

    def __repr__(self) -> str:
        # Ключ в repr не выводим.
        return f"PolzaRouter(model={self._model})"

    async def complete(self, *, system_prompt: str, user_text: str) -> RouterReply:
        """Один вызов модели: при временной ошибке — одна повторная попытка, иначе RouterError.

        400 повторяется без response_format: модель могла отвергнуть json_object, но ответ всё
        равно разбирается парсером решения.
        """
        url = self._api_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }

        retry_payload: dict[str, Any]
        delay: float
        try:
            response = await self._post(url, payload)
        except RouterError as exc:
            if exc.reason not in ("timeout", "network"):
                raise
            retry_payload, delay = payload, self._retry_delay_sec
        else:
            status = response.status_code
            if status == 200:
                return self._parse(response)
            if status == 400:
                retry_payload = {k: v for k, v in payload.items() if k != "response_format"}
                delay = 0.0
            elif status in _RETRY_STATUSES:
                retry_payload, delay = payload, self._retry_delay(response)
            else:
                raise RouterError(f"http_{status}")

        if delay > 0:
            await self._sleep(delay)
        response = await self._post(url, retry_payload)
        if response.status_code == 200:
            return self._parse(response)
        raise RouterError(f"http_{response.status_code}")

    async def _post(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        """Один запрос под жёстким дедлайном. Сетевые ошибки — RouterError без деталей."""
        try:
            async with asyncio.timeout(self._timeout_sec):
                return await self._http.post(
                    url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                    timeout=httpx.Timeout(self._timeout_sec, connect=CONNECT_TIMEOUT_SEC),
                )
        except (TimeoutError, httpx.TimeoutException):
            raise RouterError("timeout") from None
        except httpx.HTTPError:
            raise RouterError("network") from None

    def _retry_delay(self, response: httpx.Response) -> float:
        """Пауза из Retry-After в секундах, не больше MAX_RETRY_AFTER_SEC; иначе стандартная.

        Формат HTTP-date не разбирается: в таком случае хватает стандартной паузы.
        """
        value = response.headers.get("Retry-After", "").strip()
        if value.isdigit():
            return min(float(value), MAX_RETRY_AFTER_SEC)
        return self._retry_delay_sec

    @staticmethod
    def _parse(response: httpx.Response) -> RouterReply:
        """Достаёт content и model из тела. Любая форма, кроме ожидаемой, — invalid_response."""
        try:
            body = response.json()
        except ValueError:
            raise RouterError("invalid_response") from None
        if not isinstance(body, dict):
            raise RouterError("invalid_response")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RouterError("invalid_response")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RouterError("invalid_response")
        content = message.get("content")
        if not isinstance(content, str) or content.strip() == "":
            raise RouterError("invalid_response")
        model = body.get("model")
        return RouterReply(content=content, model=model if isinstance(model, str) else None)
