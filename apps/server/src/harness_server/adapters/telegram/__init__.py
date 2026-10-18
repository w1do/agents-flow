"""Адаптер Telegram Bot API: Protocol, клиент на httpx и фейк для тестов."""

from harness_server.adapters.telegram.client import HttpxTelegramClient
from harness_server.adapters.telegram.fake import FakeTelegramClient
from harness_server.adapters.telegram.protocol import TelegramClient
from harness_server.adapters.telegram.types import (
    FileTooLarge,
    InlineButton,
    InlineKeyboard,
    MessageNotEditable,
    TelegramError,
    TelegramFile,
)

__all__ = [
    "FakeTelegramClient",
    "FileTooLarge",
    "HttpxTelegramClient",
    "InlineButton",
    "InlineKeyboard",
    "MessageNotEditable",
    "TelegramClient",
    "TelegramError",
    "TelegramFile",
]
