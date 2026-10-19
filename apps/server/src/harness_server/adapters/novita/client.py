"""Адаптер Novita: NovitaSandboxProvider поверх нативного AsyncSandbox (D-35).

Единственный модуль, который импортирует novita_sandbox. Ключ и домен передаются явно из Settings,
а не через ENV процесса. Исключения SDK переводятся в ошибки адаптера, их текст не копируется.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

import httpx
from novita_sandbox.core import AsyncSandbox, CommandExitException
from novita_sandbox.core.exceptions import (
    FileNotFoundException,
    RateLimitException,
    SandboxException,
    SandboxNotFoundException,
    TimeoutException,
)

from harness_server.adapters.novita.errors import SandboxError, SandboxNotFound, SandboxUnavailable
from harness_server.adapters.novita.protocol import ExecResult

# Так Novita отвечает на exec и connect, когда песочницу убил таймаут (запуск 2 mvp-01, D-19).
_NOT_FOUND_TEXT: Final = "sandbox was not found"


def _translate(exc: BaseException) -> SandboxError:
    """Переводит исключение SDK или транспорта в ошибку адаптера с машинным reason.

    reason — код, а не текст SDK: текст может содержать адрес, ключ или вывод команды.
    """
    if isinstance(exc, SandboxNotFoundException):
        return SandboxNotFound("not_found")
    if isinstance(exc, TimeoutException):
        if _NOT_FOUND_TEXT in str(exc).lower():
            return SandboxNotFound("not_found")
        return SandboxUnavailable("timeout")
    if isinstance(exc, RateLimitException):
        return SandboxUnavailable("rate_limit")
    if isinstance(exc, httpx.HTTPError):
        return SandboxUnavailable("network")
    return SandboxUnavailable("sdk_error")


@contextmanager
def _sdk_errors() -> Iterator[None]:
    """Переводит ошибки SDK и httpx в SandboxError; причина (__cause__) не сохраняется.

    from None убирает цепочку исключений: в логах с exc_info не должны появиться текст команды
    или ключ из заголовков запроса.
    """
    try:
        yield
    except (SandboxException, httpx.HTTPError) as exc:
        raise _translate(exc) from None


class NovitaSandboxProvider:
    """SandboxProvider на AsyncSandbox. Подключение кэшируется по sandbox_id до паузы или ошибки.

    Ключ передаётся в каждый запрос явно (api_key=, domain=); repr не показывает ключ.
    """

    def __init__(self, *, api_key: str, domain: str | None = None) -> None:
        self._opts: dict[str, Any] = {"api_key": api_key, "domain": domain}
        self._sandboxes: dict[str, Any] = {}

    def __repr__(self) -> str:
        return "NovitaSandboxProvider()"

    async def _handle(self, sandbox_id: str) -> Any:
        """Подключение к песочнице: из кэша или через connect (он же возобновляет paused)."""
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            sandbox = await AsyncSandbox.connect(sandbox_id, **self._opts)
            self._sandboxes[sandbox_id] = sandbox
        return sandbox

    async def connect(self, sandbox_id: str) -> None:
        """Подключается к песочнице; приостановленная возобновляется."""
        with _sdk_errors():
            self._sandboxes.pop(sandbox_id, None)
            await self._handle(sandbox_id)

    async def exec(
        self,
        sandbox_id: str,
        cmd: str,
        *,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: int = 60,
    ) -> ExecResult:
        """Команда в foreground. Ненулевой код возвращается в ExecResult, а не бросается."""
        with _sdk_errors():
            sandbox = await self._handle(sandbox_id)
            try:
                result = await sandbox.commands.run(cmd, envs=envs, cwd=cwd, timeout=timeout_s)
            except CommandExitException as exc:
                return ExecResult(
                    exit_code=int(exc.exit_code),
                    stdout=str(exc.stdout),
                    stderr=str(exc.stderr),
                )
            return ExecResult(
                exit_code=int(result.exit_code),
                stdout=str(result.stdout),
                stderr=str(result.stderr),
            )

    async def write_file(self, sandbox_id: str, path: str, data: str) -> None:
        """Записывает текстовый файл."""
        with _sdk_errors():
            sandbox = await self._handle(sandbox_id)
            await sandbox.files.write(path, data)

    async def read_file(self, sandbox_id: str, path: str) -> str | None:
        """Текст файла или None, если файла нет."""
        with _sdk_errors():
            sandbox = await self._handle(sandbox_id)
            try:
                content = await sandbox.files.read(path)
            except FileNotFoundException:
                return None
            return str(content)

    async def pause(self, sandbox_id: str) -> None:
        """Пауза. Вызов на классе по sandbox_id, как у connect; кэш сбрасывается."""
        with _sdk_errors():
            await AsyncSandbox.pause(sandbox_id, **self._opts)
        self._sandboxes.pop(sandbox_id, None)

    async def extend_timeout(self, sandbox_id: str, seconds: int) -> None:
        """Продлевает жизнь песочницы на seconds от момента вызова (D-19)."""
        with _sdk_errors():
            await AsyncSandbox.set_timeout(sandbox_id, seconds, **self._opts)
