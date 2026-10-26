"""Протокол провайдера песочницы, независимый от конкретного внешнего API."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ExecResult:
    """Итог команды. Ненулевой exit_code — обычный результат."""

    exit_code: int
    stdout: str
    stderr: str


class SandboxProvider(Protocol):
    """Асинхронные операции над песочницей по id провайдера."""

    async def connect(self, sandbox_id: str) -> None:
        """Проверяет, что песочница доступна."""
        ...

    async def exec(
        self,
        sandbox_id: str,
        cmd: str,
        *,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float = 60,
    ) -> ExecResult:
        """Выполняет команду и возвращает код и ограниченный вывод."""
        ...

    async def write_file(self, sandbox_id: str, path: str, data: str) -> None:
        """Атомарно записывает текстовый файл."""
        ...

    async def read_file(self, sandbox_id: str, path: str) -> str | None:
        """Читает текстовый файл; отсутствующий файл возвращает None."""
        ...

    async def pause(self, sandbox_id: str) -> None:
        """Приостанавливает песочницу, если это поддерживает провайдер."""
        ...
