"""Клиент Bot API на httpx (D-14). Токен бота — часть URL, поэтому ошибки здесь очищаются от URL."""

import asyncio
from collections.abc import Sequence
from typing import Any, Final

import httpx

from harness_server.adapters.telegram.types import (
    FileTooLarge,
    InlineKeyboard,
    MessageNotEditable,
    TelegramError,
    TelegramFile,
)

TELEGRAM_API_URL = "https://api.telegram.org"
# Голосовое до 20 МиБ по каналу Telegram укладывается в минуту с запасом; дольше — зависший поток.
DOWNLOAD_TIMEOUT_SEC: Final = 60.0

# Подстроки описания Telegram для недоступного сообщения. Точных текстов Telegram не публикует,
# поэтому сравниваем подстроки в нижнем регистре, а не весь текст (design, Risks).
_NOT_EDITABLE_MARKERS = ("can't be edited", "to edit not found", "message_id_invalid")


class HttpxTelegramClient:
    """Тонкий клиент Bot API на httpx (D-14). httpx.AsyncClient принадлежит вызывающему."""

    def __init__(
        self, token: str, http: httpx.AsyncClient, *, base_url: str = TELEGRAM_API_URL
    ) -> None:
        self._token = token
        self._http = http
        self._base_url = base_url

    def __repr__(self) -> str:
        # Токен в repr не выводим: объект попадает в отладочные выводы и логи.
        return "HttpxTelegramClient()"

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        """Вызывает метод Bot API и возвращает result. Ошибки — только TelegramError, без URL."""
        url = f"{self._base_url}/bot{self._token}/{method}"
        try:
            response = await self._http.post(url, json=payload)
        except httpx.HTTPError as exc:
            # Имя класса, а не текст: текст httpx-исключения может содержать URL с токеном.
            raise TelegramError(method, None, type(exc).__name__) from None
        try:
            body = response.json()
        except ValueError:
            raise TelegramError(method, response.status_code, "invalid response") from None
        if not isinstance(body, dict):
            raise TelegramError(method, response.status_code, "invalid response")
        if body.get("ok") is True:
            return body.get("result")
        error_code = body.get("error_code")
        description = body.get("description")
        raise TelegramError(
            method,
            error_code if isinstance(error_code, int) else response.status_code,
            description if isinstance(description, str) else "unknown error",
        )

    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: InlineKeyboard | None = None
    ) -> int:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup.to_api()
        result = await self._call("sendMessage", payload)
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(message_id, int):
            raise TelegramError("sendMessage", None, "invalid response")
        return message_id

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: InlineKeyboard | None = None,
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup.to_api()
        try:
            await self._call("editMessageText", payload)
        except TelegramError as exc:
            description = exc.description.lower()
            # Текст уже такой же: для повторной правки это успех, а не ошибка.
            if exc.error_code == 400 and "message is not modified" in description:
                return
            if exc.error_code == 400 and any(
                marker in description for marker in _NOT_EDITABLE_MARKERS
            ):
                raise MessageNotEditable(exc.method, exc.error_code, exc.description) from None
            raise

    async def answer_callback_query(
        self, callback_query_id: str, *, text: str | None = None
    ) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
        await self._call("answerCallbackQuery", payload)

    async def get_file(self, file_id: str) -> TelegramFile:
        result = await self._call("getFile", {"file_id": file_id})
        if not isinstance(result, dict):
            raise TelegramError("getFile", None, "invalid response")
        returned_id = result.get("file_id")
        file_path = result.get("file_path")
        file_size = result.get("file_size")
        if not isinstance(returned_id, str):
            raise TelegramError("getFile", None, "invalid response")
        return TelegramFile(
            file_id=returned_id,
            file_path=file_path if isinstance(file_path, str) else None,
            file_size=file_size if isinstance(file_size, int) else None,
        )

    async def download_file(self, file_path: str, *, max_bytes: int) -> bytes:
        # file_path пришёл из ответа Telegram, но путь с «..» или абсолютный нельзя принимать.
        if file_path.startswith("/") or ".." in file_path:
            raise TelegramError("downloadFile", None, "invalid file path")
        url = f"{self._base_url}/file/bot{self._token}/{file_path}"
        chunks: list[bytes] = []
        total = 0
        try:
            # Общий дедлайн на всё скачивание: медленный поток не держит worker бесконечно (S5).
            async with asyncio.timeout(DOWNLOAD_TIMEOUT_SEC):
                async with self._http.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise TelegramError("downloadFile", response.status_code, "download failed")
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FileTooLarge("downloadFile", None, "file too large")
                        chunks.append(chunk)
        except TimeoutError:
            raise TelegramError("downloadFile", None, "download timeout") from None
        except httpx.HTTPError as exc:
            raise TelegramError("downloadFile", None, type(exc).__name__) from None
        return b"".join(chunks)

    async def set_webhook(
        self, url: str, *, secret_token: str, allowed_updates: Sequence[str]
    ) -> None:
        payload: dict[str, Any] = {
            "url": url,
            "secret_token": secret_token,
            "allowed_updates": list(allowed_updates),
        }
        await self._call("setWebhook", payload)
