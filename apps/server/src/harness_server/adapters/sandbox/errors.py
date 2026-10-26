"""Ошибки общего адаптера песочницы без деталей провайдера."""


class SandboxError(Exception):
    """Базовая ошибка адаптера песочницы."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"sandbox failed: {reason}")
        self.reason = reason


class SandboxNotFound(SandboxError):
    """Песочницы с указанным id нет."""


class SandboxUnavailable(SandboxError):
    """Песочница временно недоступна."""
