"""Протокол клиента Telegram Bot API: сервисы зависят от него, а не от httpx (CLAUDE.md §3)."""

from collections.abc import Sequence
from typing import Protocol

from harness_server.adapters.telegram.types import InlineKeyboard, TelegramFile


class TelegramClient(Protocol):
    """Вызовы Bot API, нужные боту. При ошибке каждый метод бросает TelegramError или подкласс."""

    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: InlineKeyboard | None = None
    ) -> int:
        """Отправляет текст без разметки и возвращает message_id."""
        ...

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: InlineKeyboard | None = None,
    ) -> None:
        """Меняет текст. «Текст не изменился» — успех; недоступно — MessageNotEditable."""
        ...

    async def answer_callback_query(
        self, callback_query_id: str, *, text: str | None = None
    ) -> None:
        """Снимает индикатор загрузки с кнопки; text, если задан, показывается пользователю."""
        ...

    async def get_file(self, file_id: str) -> TelegramFile:
        """Возвращает путь и размер файла для скачивания."""
        ...

    async def download_file(self, file_path: str, *, max_bytes: int) -> bytes:
        """Скачивает файл целиком; больше max_bytes — FileTooLarge."""
        ...

    async def set_webhook(
        self, url: str, *, secret_token: str, allowed_updates: Sequence[str]
    ) -> None:
        """Регистрирует адрес webhook вместе с секретом и списком типов апдейтов."""
        ...
