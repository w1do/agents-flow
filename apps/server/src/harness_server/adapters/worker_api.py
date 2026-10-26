"""HTTP-адаптер канала worker: ограниченные повторы и ошибки без URL, тела и токенов."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
from pydantic import BaseModel


class WorkerAPIError(Exception):
    """Безопасная ошибка транспорта для журналов worker."""

    def __init__(self, reason: str, status_code: int | None = None) -> None:
        super().__init__(f"worker API: {reason}")
        self.reason = reason
        self.status_code = status_code


class WorkerAPI(Protocol):
    """Транспорт данных; DTO проверяет клиент, правила применяет сервер."""

    async def post(
        self, path: str, body: BaseModel | None = None, *, token: str | None = None
    ) -> object: ...


class HttpWorkerAPI:
    """Повторяет тот же запрос при сетевой ошибке и 5xx; редиректы запрещены."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        worker_token: str,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._worker_token = worker_token
        self.sleep = sleep

    async def post(
        self, path: str, body: BaseModel | None = None, *, token: str | None = None
    ) -> object:
        """Три попытки, backoff 0.25/0.5 с; нет повтора после 4xx."""
        headers = {"Authorization": f"Bearer {self._worker_token}"}
        if token is not None:
            headers["X-Task-Token"] = token
        for attempt in range(3):
            try:
                response = await self.http.post(
                    self.base_url + path,
                    headers=headers,
                    json=None if body is None else body.model_dump(mode="json"),
                    follow_redirects=False,
                )
            except httpx.TransportError:
                if attempt == 2:
                    raise WorkerAPIError("network") from None
            else:
                if response.status_code < 500 or attempt == 2:
                    if not 200 <= response.status_code < 300:
                        raise WorkerAPIError(f"http_{response.status_code}", response.status_code)
                    if response.status_code == 204:
                        return None
                    try:
                        result: object = response.json()
                        return result
                    except ValueError:
                        raise WorkerAPIError("invalid_response") from None
            await self.sleep(0.25 * 2**attempt)
        raise WorkerAPIError("network")


class FakeWorkerAPI:
    """Записанные ответы без сети; сохраняет пути и тела, но не токены."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, BaseModel | None]] = []

    async def post(
        self, path: str, body: BaseModel | None = None, *, token: str | None = None
    ) -> object:
        """Возвращает следующий записанный ответ и фиксирует несекретные аргументы."""
        self.calls.append((path, body))
        if not self.responses:
            raise WorkerAPIError("missing_fixture")
        return self.responses.pop(0)
