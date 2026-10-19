"""Ошибки адаптера песочницы Novita. Сообщение — только класс или код сбоя SDK.

Текст исключений SDK не попадает в сообщение: он может содержать вывод команды, путь или домен.
Поэтому и логи, и ответы видят только машинный reason.
"""


class SandboxError(Exception):
    """Базовая ошибка адаптера песочницы."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"sandbox failed: {reason}")
        self.reason = reason


class SandboxNotFound(SandboxError):
    """Песочницы нет: удалена по таймауту (D-19) или id неверный."""


class SandboxUnavailable(SandboxError):
    """Песочница временно недоступна: лимит запросов, сеть, таймаут или прочий сбой провайдера."""
