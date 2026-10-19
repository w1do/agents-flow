"""Контрактные тесты NovitaSandboxProvider без сети: AsyncSandbox подменяется на время теста.

Проверяются: передача ключа и домена явно, перевод ошибок SDK в SandboxNotFound/SandboxUnavailable,
ненулевой код exec как ExecResult, отсутствие файла как None, текст ошибок без ключа.
"""

from typing import Any

import pytest
from harness_server.adapters.novita import (
    ExecResult,
    NovitaSandboxProvider,
    SandboxNotFound,
    SandboxUnavailable,
)
from harness_server.adapters.novita import client as novita_client
from novita_sandbox.core import (
    CommandExitException,
    CommandResult,
    FileNotFoundException,
    RateLimitException,
    SandboxException,
    SandboxNotFoundException,
    TimeoutException,
)

pytestmark = pytest.mark.asyncio

SANDBOX_ID = "sbx-test-1"
KEY = "nk-test-key-0123456789"
DOMAIN = "test.sandbox.example"


class FakeSdkSandbox:
    """Экземпляр, который возвращает connect: commands и files с программируемым поведением."""

    def __init__(self) -> None:
        self.run_result: CommandResult = CommandResult(
            stderr="", stdout="ok\n", exit_code=0, error=None
        )
        self.run_error: BaseException | None = None
        self.read_result: str = "file body"
        self.read_error: BaseException | None = None
        self.run_calls: list[dict[str, Any]] = []
        self.write_calls: list[tuple[str, str]] = []
        self.commands = self
        self.files = self

    async def run(self, cmd: str, **kwargs: Any) -> CommandResult:
        self.run_calls.append({"cmd": cmd, **kwargs})
        if self.run_error is not None:
            raise self.run_error
        return self.run_result

    async def read(self, path: str, **kwargs: Any) -> str:
        if self.read_error is not None:
            raise self.read_error
        return self.read_result

    async def write(self, path: str, data: str, **kwargs: Any) -> None:
        self.write_calls.append((path, data))


class SdkLog:
    """Что SDK получил на статических вызовах connect, pause, set_timeout."""

    def __init__(self) -> None:
        self.opts: list[dict[str, Any]] = []
        self.paused: list[str] = []
        self.timeouts: list[tuple[str, int]] = []


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeSdkSandbox, SdkLog]:
    instance = FakeSdkSandbox()
    log = SdkLog()

    class FakeAsyncSandbox:
        @staticmethod
        async def connect(sandbox_id: str, **opts: Any) -> FakeSdkSandbox:
            assert sandbox_id == SANDBOX_ID
            log.opts.append(opts)
            return instance

        @staticmethod
        async def pause(sandbox_id: str, **opts: Any) -> str:
            log.paused.append(sandbox_id)
            return sandbox_id

        @staticmethod
        async def set_timeout(sandbox_id: str, seconds: int, **opts: Any) -> None:
            log.timeouts.append((sandbox_id, seconds))

    monkeypatch.setattr(novita_client, "AsyncSandbox", FakeAsyncSandbox)
    return instance, log


def _provider() -> NovitaSandboxProvider:
    return NovitaSandboxProvider(api_key=KEY, domain=DOMAIN)


async def test_connect_passes_key_and_domain_explicitly(
    sdk: tuple[FakeSdkSandbox, SdkLog],
) -> None:
    _, log = sdk

    await _provider().connect(SANDBOX_ID)

    assert log.opts == [{"api_key": KEY, "domain": DOMAIN}]


async def test_exec_returns_result_with_env_and_cwd(sdk: tuple[FakeSdkSandbox, SdkLog]) -> None:
    instance, _ = sdk

    result = await _provider().exec(
        SANDBOX_ID, "git status", envs={"A": "1"}, cwd="/work", timeout_s=30
    )

    assert result == ExecResult(exit_code=0, stdout="ok\n", stderr="")
    assert instance.run_calls == [
        {"cmd": "git status", "envs": {"A": "1"}, "cwd": "/work", "timeout": 30}
    ]


async def test_nonzero_exit_is_returned_not_raised(sdk: tuple[FakeSdkSandbox, SdkLog]) -> None:
    instance, _ = sdk
    instance.run_error = CommandExitException(
        stderr="fatal: boom", stdout="partial", exit_code=2, error=None
    )

    result = await _provider().exec(SANDBOX_ID, "false")

    assert result == ExecResult(exit_code=2, stdout="partial", stderr="fatal: boom")


async def test_sandbox_not_found_exception_maps_to_not_found(
    sdk: tuple[FakeSdkSandbox, SdkLog],
) -> None:
    instance, _ = sdk
    instance.run_error = SandboxNotFoundException("gone")

    with pytest.raises(SandboxNotFound):
        await _provider().exec(SANDBOX_ID, "ls")


async def test_timeout_with_not_found_text_maps_to_not_found(
    sdk: tuple[FakeSdkSandbox, SdkLog],
) -> None:
    instance, _ = sdk
    instance.run_error = TimeoutException("Sandbox was not found while running the command")

    with pytest.raises(SandboxNotFound):
        await _provider().exec(SANDBOX_ID, "ls")


async def test_plain_timeout_maps_to_unavailable(sdk: tuple[FakeSdkSandbox, SdkLog]) -> None:
    instance, _ = sdk
    instance.run_error = TimeoutException("deadline exceeded")

    with pytest.raises(SandboxUnavailable) as info:
        await _provider().exec(SANDBOX_ID, "sleep 999")

    assert info.value.reason == "timeout"


async def test_missing_file_reads_as_none(sdk: tuple[FakeSdkSandbox, SdkLog]) -> None:
    instance, _ = sdk
    instance.read_error = FileNotFoundException("no such file")

    assert await _provider().read_file(SANDBOX_ID, "/home/user/x.json") is None


async def test_existing_file_is_read(sdk: tuple[FakeSdkSandbox, SdkLog]) -> None:
    instance, _ = sdk
    instance.read_result = '{"status": "done"}'

    assert await _provider().read_file(SANDBOX_ID, "/home/user/status.json") == '{"status": "done"}'


async def test_write_file_passes_path_and_data(sdk: tuple[FakeSdkSandbox, SdkLog]) -> None:
    instance, _ = sdk

    await _provider().write_file(SANDBOX_ID, "/home/user/run.sh", "echo hi\n")

    assert instance.write_calls == [("/home/user/run.sh", "echo hi\n")]


async def test_rate_limit_maps_to_unavailable_without_secrets(
    sdk: tuple[FakeSdkSandbox, SdkLog],
) -> None:
    instance, _ = sdk
    instance.run_error = RateLimitException(f"limit for {KEY} at {DOMAIN}")

    with pytest.raises(SandboxUnavailable) as info:
        await _provider().exec(SANDBOX_ID, "ls")

    assert info.value.reason == "rate_limit"
    assert KEY not in str(info.value)
    assert DOMAIN not in str(info.value)


async def test_sdk_error_text_is_not_chained(sdk: tuple[FakeSdkSandbox, SdkLog]) -> None:
    instance, _ = sdk
    instance.run_error = SandboxException(f"curl https://{KEY}@{DOMAIN}")

    with pytest.raises(SandboxUnavailable) as info:
        await _provider().exec(SANDBOX_ID, "curl")

    # from None: текст исходного исключения SDK (с адресом и ключом) не попадает в трассировку.
    assert info.value.__suppress_context__ is True
    assert KEY not in str(info.value)


async def test_pause_and_extend_timeout_use_sandbox_id(sdk: tuple[FakeSdkSandbox, SdkLog]) -> None:
    _, log = sdk

    await _provider().pause(SANDBOX_ID)
    await _provider().extend_timeout(SANDBOX_ID, 1200)

    assert log.paused == [SANDBOX_ID]
    assert log.timeouts == [(SANDBOX_ID, 1200)]
