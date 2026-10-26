"""Фейк песочницы для тестов: файлы в памяти и журнал без значений env."""

from dataclasses import dataclass, field
from typing import Final

from harness_server.adapters.sandbox.errors import SandboxNotFound
from harness_server.adapters.sandbox.protocol import ExecResult

_DEFAULT_RESULT: Final = ExecResult(exit_code=0, stdout="", stderr="")


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """Одна запись журнала; значения env намеренно не сохраняются."""

    method: str
    cmd: str | None
    env_keys: tuple[str, ...]
    cwd: str | None


@dataclass(slots=True)
class _Response:
    prefix: str
    result: ExecResult


@dataclass(slots=True)
class FakeSandbox:
    """SandboxProvider для одной песочницы; kill имитирует удаление провайдером."""

    sandbox_id: str = "sbx-fake"
    paused: bool = False
    journal: list[JournalEntry] = field(default_factory=list)
    _files: dict[str, str] = field(default_factory=dict)
    _responses: list[_Response] = field(default_factory=list)
    _env_values: dict[str, str] = field(default_factory=dict)
    _killed: bool = False

    def respond(
        self, prefix: str, *, exit_code: int = 0, stdout: str = "", stderr: str = ""
    ) -> None:
        """Задаёт ответ exec; побеждает самый длинный префикс."""
        self._responses.append(
            _Response(prefix, ExecResult(exit_code=exit_code, stdout=stdout, stderr=stderr))
        )

    def kill(self) -> None:
        """После удаления все обращения возвращают SandboxNotFound."""
        self._killed = True

    def received_env(self, key: str) -> str | None:
        """Возвращает последнее переданное значение вне журнала."""
        return self._env_values.get(key)

    def files_containing(self, needle: str) -> list[str]:
        """Ищет текст в файлах фейка для проверок отсутствия секретов."""
        if not needle:
            raise ValueError("needle must not be empty")
        return sorted(path for path, text in self._files.items() if needle in text)

    async def connect(self, sandbox_id: str) -> None:
        self._check(sandbox_id)
        self.paused = False
        self.journal.append(JournalEntry("connect", None, (), None))

    async def exec(
        self,
        sandbox_id: str,
        cmd: str,
        *,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float = 60,
    ) -> ExecResult:
        self._check(sandbox_id)
        env_keys = tuple(sorted(envs)) if envs else ()
        self.journal.append(JournalEntry("exec", cmd, env_keys, cwd))
        if envs:
            self._env_values.update(envs)
        matches = [response for response in self._responses if cmd.startswith(response.prefix)]
        if not matches:
            return _DEFAULT_RESULT
        return max(matches, key=lambda response: len(response.prefix)).result

    async def write_file(self, sandbox_id: str, path: str, data: str) -> None:
        self._check(sandbox_id)
        self.journal.append(JournalEntry("write_file", path, (), None))
        self._files[path] = data

    async def read_file(self, sandbox_id: str, path: str) -> str | None:
        self._check(sandbox_id)
        self.journal.append(JournalEntry("read_file", path, (), None))
        return self._files.get(path)

    async def pause(self, sandbox_id: str) -> None:
        self._check(sandbox_id)
        self.paused = True
        self.journal.append(JournalEntry("pause", None, (), None))

    def _check(self, sandbox_id: str) -> None:
        if self._killed or sandbox_id != self.sandbox_id:
            raise SandboxNotFound("not_found")
