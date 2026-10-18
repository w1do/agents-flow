"""Фейк клиента Telegram для тестов: пишет вызовы в списки и хранит текущий текст сообщений."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from harness_server.adapters.telegram.types import (
    FileTooLarge,
    InlineKeyboard,
    MessageNotEditable,
    TelegramError,
    TelegramFile,
)


@dataclass
class SentMessage:
    """Отправленное сообщение, как его видит фейк."""

    chat_id: int
    message_id: int
    text: str
    reply_markup: InlineKeyboard | None


@dataclass
class EditedMessage:
    """Правка сообщения: что и на что поменяли."""

    chat_id: int
    message_id: int
    text: str
    reply_markup: InlineKeyboard | None


class FakeTelegramClient:
    """Фейк TelegramClient: пишет вызовы в списки, хранит текущий текст сообщений."""

    def __init__(self, *, files: Mapping[str, bytes] | None = None) -> None:
        self.sent: list[SentMessage] = []
        self.edits: list[EditedMessage] = []
        self.callback_answers: list[tuple[str, str | None]] = []
        self.webhooks: list[tuple[str, str, tuple[str, ...]]] = []
        self.files: dict[str, bytes] = dict(files or {})
        self.texts: dict[int, str] = {}  # message_id → текущий текст
        self.not_editable: set[int] = set()
        # Если задано — каждый метод бросает эту ошибку, чтобы проверить сбой Telegram.
        self.fail_with: TelegramError | None = None
        self._next_message_id = 100

    def _raise_if_failing(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: InlineKeyboard | None = None
    ) -> int:
        self._raise_if_failing()
        message_id = self._next_message_id
        self._next_message_id += 1
        self.sent.append(SentMessage(chat_id, message_id, text, reply_markup))
        self.texts[message_id] = text
        return message_id

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: InlineKeyboard | None = None,
    ) -> None:
        self._raise_if_failing()
        if message_id in self.not_editable or message_id not in self.texts:
            raise MessageNotEditable(
                "editMessageText", 400, "Bad Request: message to edit not found"
            )
        self.edits.append(EditedMessage(chat_id, message_id, text, reply_markup))
        self.texts[message_id] = text

    async def answer_callback_query(
        self, callback_query_id: str, *, text: str | None = None
    ) -> None:
        self._raise_if_failing()
        self.callback_answers.append((callback_query_id, text))

    async def get_file(self, file_id: str) -> TelegramFile:
        self._raise_if_failing()
        if file_id not in self.files:
            raise TelegramError("getFile", 400, "Bad Request: invalid file_id")
        return TelegramFile(file_id, f"voice/{file_id}.oga", len(self.files[file_id]))

    async def download_file(self, file_path: str, *, max_bytes: int) -> bytes:
        self._raise_if_failing()
        file_id = file_path.removeprefix("voice/").removesuffix(".oga")
        if file_id not in self.files:
            raise TelegramError("downloadFile", 404, "download failed")
        data = self.files[file_id]
        if len(data) > max_bytes:
            raise FileTooLarge("downloadFile", None, "file too large")
        return data

    async def set_webhook(
        self, url: str, *, secret_token: str, allowed_updates: Sequence[str]
    ) -> None:
        self._raise_if_failing()
        self.webhooks.append((url, secret_token, tuple(allowed_updates)))
