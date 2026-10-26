"""Безопасный локальный SandboxProvider для постоянной машины агента."""

import asyncio
import os
import re
import signal
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Final

from harness_server.adapters.sandbox.errors import SandboxNotFound, SandboxUnavailable
from harness_server.adapters.sandbox.protocol import ExecResult
from harness_server.services.machine import RootUserError, require_non_root

_ENV_KEY_RE: Final = re.compile(r"^[A-Z_][A-Z0-9_]*$")
# Прокси нужны машине агента для выхода в сеть; это не секреты и не значения ключей.
_PROXY_ENV_NAMES: Final = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
_OUTPUT_LIMIT_BYTES: Final = 1_048_576
_READ_CHUNK_BYTES: Final = 65_536


class LocalSandboxProvider:
    """Исполняет команды на машине агента, не наследуя окружение worker."""

    def __init__(self, provider_id: str = "local") -> None:
        self.provider_id = provider_id

    async def connect(self, sandbox_id: str) -> None:
        """Проверяет id, отдельного непривилегированного пользователя и его HOME."""
        self._check_id(sandbox_id)
        try:
            require_non_root()
        except RootUserError:
            raise SandboxUnavailable("root") from None
        try:
            result = await self.exec(sandbox_id, "true")
            home_exists = await asyncio.to_thread(Path(self._environment()["HOME"]).is_dir)
            if result.exit_code != 0 or not home_exists:
                raise SandboxUnavailable("unreachable")
        except (OSError, SandboxUnavailable) as exc:
            if isinstance(exc, SandboxUnavailable) and exc.reason == "root":
                raise
            raise SandboxUnavailable("unreachable") from None

    async def exec(
        self,
        sandbox_id: str,
        cmd: str,
        *,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float = 60,
    ) -> ExecResult:
        """Запускает bash в отдельной группе; таймаут убивает всю эту группу."""
        self._check_id(sandbox_id)
        environment = self._environment(envs)
        process = await asyncio.create_subprocess_exec(
            "bash",
            "-lc",
            cmd,
            cwd=cwd,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(
            _read_limited(process.stdout), name="local-sandbox-stdout"
        )
        stderr_task = asyncio.create_task(
            _read_limited(process.stderr), name="local-sandbox-stderr"
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                _wait_for_process_output(process, stdout_task, stderr_task), timeout=timeout_s
            )
        except TimeoutError:
            await _stop_process(process, stdout_task, stderr_task)
            raise SandboxUnavailable("timeout") from None
        except asyncio.CancelledError:
            await _stop_process(process, stdout_task, stderr_task)
            raise
        return ExecResult(process.returncode or 0, stdout, stderr)

    async def write_file(self, sandbox_id: str, path: str, data: str) -> None:
        """Атомарно записывает UTF-8 файл с правами 0600 в каталоге 0700."""
        self._check_id(sandbox_id)
        target = _absolute_path(path)
        await asyncio.to_thread(_write_private_file, target, data)

    async def read_file(self, sandbox_id: str, path: str) -> str | None:
        """Читает UTF-8 файл; тильда не разворачивается, отсутствующий файл — None."""
        self._check_id(sandbox_id)
        target = _absolute_path(path)
        try:
            return await asyncio.to_thread(target.read_text, encoding="utf-8")
        except FileNotFoundError:
            return None

    async def pause(self, sandbox_id: str) -> None:
        """Локальная машина не приостанавливается: освобождается только запись БД."""
        self._check_id(sandbox_id)

    def _check_id(self, sandbox_id: str) -> None:
        if sandbox_id != self.provider_id:
            raise SandboxNotFound("not_found")

    def _environment(self, envs: Mapping[str, str] | None = None) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "USER", "LOGNAME", "LANG", "TERM", *_PROXY_ENV_NAMES}
            or key.startswith("LC_")
        }
        if "HOME" not in environment:
            environment["HOME"] = str(Path.home())
        for key, value in (envs or {}).items():
            if not _ENV_KEY_RE.fullmatch(key):
                raise ValueError(f"invalid environment variable name: {key}")
            if "\0" in value:
                raise ValueError(f"environment variable {key} contains NUL")
            environment[key] = value
        return environment


async def _read_limited(stream: asyncio.StreamReader) -> str:
    retained = bytearray()
    while chunk := await stream.read(_READ_CHUNK_BYTES):
        remaining = _OUTPUT_LIMIT_BYTES - len(retained)
        if remaining > 0:
            retained.extend(chunk[:remaining])
    return retained.decode("utf-8", errors="replace")


def _kill_process_group(pid: int) -> None:
    with suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


async def _stop_process(
    process: asyncio.subprocess.Process,
    stdout_task: asyncio.Task[str],
    stderr_task: asyncio.Task[str],
) -> None:
    """Останавливает группу и дочитывает пайпы, чтобы отмена не оставляла фоновых задач."""
    _kill_process_group(process.pid)
    await process.wait()
    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)


async def _wait_for_process_output(
    process: asyncio.subprocess.Process,
    stdout_task: asyncio.Task[str],
    stderr_task: asyncio.Task[str],
) -> tuple[str, str]:
    """Ждёт лидера и закрытия его пайпов, которые может удерживать потомок группы."""
    await process.wait()
    stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
    return stdout, stderr


def _absolute_path(path: str) -> Path:
    target = Path(path)
    if not target.is_absolute():
        raise ValueError("sandbox file path must be absolute")
    return target


def _write_private_file(target: Path, data: str) -> None:
    _create_private_parents(target.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            descriptor = -1
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except BaseException:
        if descriptor != -1:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)
        raise


def _create_private_parents(parent: Path) -> None:
    """Создаёт только отсутствующие компоненты пути с 0700, не меняя чужие каталоги."""
    current = Path(parent.anchor)
    for component in parent.parts[1:]:
        current /= component
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            continue
        os.chmod(current, 0o700)
