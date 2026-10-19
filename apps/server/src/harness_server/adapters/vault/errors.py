"""Ошибки адаптера vault. Сообщение — только причина и ссылка service/name.

Значение секрета, URL и токен vault в текст ошибки не попадают: его видят логи и ответы CLI.
"""

from typing import Literal

VaultErrorReason = Literal[
    "not_configured",
    "unavailable",
    "timeout",
    "tool_error",
    "invalid_response",
]


class VaultError(Exception):
    """Ключ из vault не получен. reason — машинная причина из VaultErrorReason."""

    def __init__(self, reason: VaultErrorReason, *, ref: str | None = None) -> None:
        # ref — только service/name, без проекта и значения: этого хватает, чтобы найти запись.
        detail = f" ({ref})" if ref else ""
        super().__init__(f"vault failed: {reason}{detail}")
        self.reason = reason
        self.ref = ref
