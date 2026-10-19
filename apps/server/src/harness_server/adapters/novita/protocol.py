"""Протокол провайдера песочниц (mvp-06, design 2). Сервисы зависят только от него, не от SDK."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ExecResult:
    """Итог команды. Ненулевой exit_code — не исключение, а обычный результат (D-35)."""

    exit_code: int
    stdout: str
    stderr: str


class SandboxProvider(Protocol):
    """Операции над песочницей по её id у провайдера. Все методы async.

    Ошибки — SandboxNotFound и SandboxUnavailable из adapters/novita/errors.py.
    """

    async def connect(self, sandbox_id: str) -> None:
        """Подключается к песочнице; приостановленная возобновляется."""
        ...

    async def exec(
        self,
        sandbox_id: str,
        cmd: str,
        *,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: int = 60,
    ) -> ExecResult:
        """Выполняет команду в foreground и возвращает код и вывод.

        envs действуют только для этой команды (D-37): значения не сохраняются в песочнице.
        """
        ...

    async def write_file(self, sandbox_id: str, path: str, data: str) -> None:
        """Записывает текстовый файл; родительский каталог должен существовать."""
        ...

    async def read_file(self, sandbox_id: str, path: str) -> str | None:
        """Читает текстовый файл. Если файла нет — None, это не ошибка."""
        ...

    async def pause(self, sandbox_id: str) -> None:
        """Ставит песочницу на паузу; файлы сохраняются (mvp-01)."""
        ...

    async def extend_timeout(self, sandbox_id: str, seconds: int) -> None:
        """Продлевает жизнь песочницы: отсчёт от вызова, а не от создания (D-19)."""
        ...
