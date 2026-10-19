"""Фейк песочницы для тестов: файлы в памяти, журнал вызовов, программируемый exec. Без сети.

Журнал не содержит значений env (только ключи), как и реальный журнал сервера. Значения env фейк
держит отдельно и отдаёт через received_env: так тест проверяет, что секрет ушёл в команду, но не
записан в журнал. Проверка «значение не лежит на диске» — через files_containing.
"""

from dataclasses import dataclass, field
from typing import Final

from harness_server.adapters.novita.errors import SandboxNotFound
from harness_server.adapters.novita.protocol import ExecResult

_DEFAULT_RESULT: Final = ExecResult(exit_code=0, stdout="", stderr="")


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """Одна запись журнала. cmd — команда для exec и путь для файловых операций."""

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
    """SandboxProvider для одной песочницы sandbox_id. Ненулевой код exec — обычный ExecResult.

    kill() имитирует удалённую песочницу: дальше любой вызов бросает SandboxNotFound.
    """

    sandbox_id: str = "sbx-fake"
    paused: bool = False
    timeout_s: int | None = None
    journal: list[JournalEntry] = field(default_factory=list)
    _files: dict[str, str] = field(default_factory=dict)
    _responses: list[_Response] = field(default_factory=list)
    _env_values: dict[str, str] = field(default_factory=dict)
    _killed: bool = False

    def respond(
        self, prefix: str, *, exit_code: int = 0, stdout: str = "", stderr: str = ""
    ) -> None:
        """Задаёт ответ exec для команд, начинающихся с prefix. Побеждает самый длинный префикс."""
        self._responses.append(
            _Response(prefix, ExecResult(exit_code=exit_code, stdout=stdout, stderr=stderr))
        )

    def kill(self) -> None:
        """Песочница удалена провайдером: все последующие вызовы бросают SandboxNotFound."""
        self._killed = True

    def received_env(self, key: str) -> str | None:
        """Последнее значение env, переданное в exec под этим ключом. В журнале значений нет."""
        return self._env_values.get(key)

    def files_containing(self, needle: str) -> list[str]:
        """Пути файлов песочницы, в тексте которых есть needle. Для проверки «креды не на диске»."""
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
        matches = [r for r in self._responses if cmd.startswith(r.prefix)]
        if not matches:
            return _DEFAULT_RESULT
        return max(matches, key=lambda r: len(r.prefix)).result

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

    async def extend_timeout(self, sandbox_id: str, seconds: int) -> None:
        self._check(sandbox_id)
        self.timeout_s = seconds
        self.journal.append(JournalEntry("extend_timeout", None, (), None))

    def _check(self, sandbox_id: str) -> None:
        if self._killed or sandbox_id != self.sandbox_id:
            raise SandboxNotFound("not_found")
