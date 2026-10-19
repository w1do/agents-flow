"""Протокол маршрутизатора команд (Polza, D-31). Адаптер не знает про классы и workspace."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RouterReply:
    """Ответ модели: content — choices[0].message.content как есть; model — id модели из ответа."""

    content: str
    model: str | None


class RouterError(Exception):
    """Вызов не удался. reason — короткий машинный код; без ключа, URL и текста ответа провайдера.

    reason: "timeout", "network", "http_<код>", "invalid_response".
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"router failed: {reason}")
        self.reason = reason


class Router(Protocol):
    """Маршрутизатор: один запрос к LLM с системным промптом и текстом владельца."""

    async def complete(self, *, system_prompt: str, user_text: str) -> RouterReply:
        """Возвращает непустой content. Любая неудача — RouterError."""
        ...
