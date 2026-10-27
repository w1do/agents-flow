from pathlib import Path, PurePosixPath
from typing import Protocol
from asyncio import timeout
from math import isfinite

from app.integrations import http

MAX_AUDIO_BYTES = 20 * 1024 * 1024
OPERATION_TIMEOUT = 30


class TelegramError(RuntimeError):
    def __init__(self, message, retry_after=None, retry_scope="chat"):
        super().__init__(message)
        self.retry_after = retry_after
        self.retry_scope = retry_scope


class Bot(Protocol):
    async def send_message(self, chat_id: str, text: str, reply_markup=None) -> dict: ...
    async def answer_callback(self, callback_id: str, text: str) -> None: ...
    async def download(self, file_id: str, destination: Path) -> None: ...


class BotClient:
    def __init__(self, token):
        self._root = f"https://api.telegram.org/bot{token}"
        self._files = f"https://api.telegram.org/file/bot{token}"

    async def _call(self, method, values):
        try:
            async with timeout(OPERATION_TIMEOUT), http.client() as client:
                response = await client.post(f"{self._root}/{method}", json=values)
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if response.status_code == 429 or body.get("error_code") == 429:
                    delay = body.get("parameters", {}).get("retry_after")
                    valid = (isinstance(delay, (int, float)) and not isinstance(delay, bool)
                             and isfinite(delay) and delay >= 0)
                    raise TelegramError("Telegram временно ограничил отправку",
                                        retry_after=delay if valid else None)
                response.raise_for_status()
                if not body.get("ok") or "result" not in body:
                    raise ValueError()
                return body["result"]
        except TelegramError:
            raise
        except Exception:
            raise TelegramError("Telegram недоступен") from None

    async def send_message(self, chat_id, text, reply_markup=None):
        values = {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
        if reply_markup:
            values["reply_markup"] = reply_markup
        return await self._call("sendMessage", values)

    async def answer_callback(self, callback_id, text):
        await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def download(self, file_id, destination):
        try:
            async with timeout(OPERATION_TIMEOUT):
                await self._download(file_id, destination)
        except TimeoutError:
            raise TelegramError("Не удалось скачать аудио вовремя. Повторите позже.") from None

    async def _download(self, file_id, destination):
        try:
            info = await self._call("getFile", {"file_id": file_id})
            path = info["file_path"]
            if (not isinstance(path, str) or path.startswith("/")
                    or ".." in PurePosixPath(path).parts or ":" in path or "?" in path):
                raise ValueError()
            async with http.client() as client:
                async with client.stream("GET", f"{self._files}/{path}") as response:
                    response.raise_for_status()
                    size = 0
                    with destination.open("wb") as audio:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_AUDIO_BYTES:
                                raise ValueError()
                            audio.write(chunk)
        except Exception:
            raise TelegramError("Не удалось скачать аудио до 20 МБ. Повторите или напишите текстом.") from None


def create_client(settings) -> Bot:
    return BotClient(settings.telegram_bot_token.get_secret_value())
