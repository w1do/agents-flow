"""Протокол распознавания речи и ошибка адаптера STT (D-05, D-29)."""

from typing import Protocol


class SttError(Exception):
    """Распознавание не удалось. Сообщение без ключа, URL с секретами и текста аудио."""


class SpeechToText(Protocol):
    """Распознавание голосового файла в текст."""

    async def transcribe(self, audio: bytes, *, filename: str, mime_type: str) -> str:
        """Возвращает непустой распознанный текст (strip). Иначе — SttError."""
        ...
