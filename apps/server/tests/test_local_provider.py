"""Контракт LocalSandboxProvider без доступа к реальной машине агента."""

import asyncio
import os
import stat
from pathlib import Path

import pytest
from harness_server.adapters.local import LocalSandboxProvider
from harness_server.adapters.local import provider as provider_module
from harness_server.adapters.sandbox import SandboxNotFound, SandboxUnavailable
from harness_server.services.machine import RootUserError, require_non_root

pytestmark = pytest.mark.asyncio


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> LocalSandboxProvider:
    """Локальный провайдер от непривилегированного пользователя с изолированным HOME."""
    monkeypatch.setattr(provider_module, "require_non_root", lambda: None)
    monkeypatch.setenv("HOME", str(tmp_path))
    return LocalSandboxProvider("agent-machine")


async def test_connect_exec_cwd_and_pause(provider: LocalSandboxProvider, tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()

    await provider.connect("agent-machine")
    result = await provider.exec("agent-machine", "printf ready; pwd", cwd=str(cwd))
    await provider.pause("agent-machine")

    assert result.exit_code == 0
    assert result.stdout == f"ready{cwd}\n"


async def test_unknown_id_is_not_found(provider: LocalSandboxProvider) -> None:
    with pytest.raises(SandboxNotFound):
        await provider.exec("other-machine", "true")


async def test_connect_refuses_root_and_reuses_machine_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _root() -> None:
        raise RootUserError("нужен отдельный пользователь без root")

    monkeypatch.setattr(provider_module, "require_non_root", _root)

    with pytest.raises(SandboxUnavailable, match="root"):
        await LocalSandboxProvider().connect("local")
    with pytest.raises(RootUserError, match="отдельный пользователь"):
        require_non_root(uid=0)


async def test_exec_does_not_leak_worker_environment_or_secret_to_argv(
    provider: LocalSandboxProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "secret-value-not-in-process-arguments"
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-private")

    result = await provider.exec(
        "agent-machine",
        "env; printf '\\nARGV='; tr '\\0' ' ' </proc/$$/cmdline",
        envs={"AGENTS_FLOW_TOKEN": secret},
    )

    assert result.exit_code == 0
    assert "DATABASE_URL=" not in result.stdout
    assert "TELEGRAM_BOT_TOKEN=" not in result.stdout
    assert f"AGENTS_FLOW_TOKEN={secret}" in result.stdout
    assert f"ARGV={secret}" not in result.stdout


@pytest.mark.parametrize("envs", [{"bad-name": "x"}, {"TOKEN": "bad\0value"}])
async def test_exec_rejects_invalid_environment(
    provider: LocalSandboxProvider, envs: dict[str, str]
) -> None:
    with pytest.raises(ValueError):
        await provider.exec("agent-machine", "true", envs=envs)


async def test_exec_bounds_output(provider: LocalSandboxProvider) -> None:
    result = await provider.exec("agent-machine", "head -c 1100000 /dev/zero | tr '\\0' x")

    assert result.exit_code == 0
    assert len(result.stdout.encode()) == provider_module._OUTPUT_LIMIT_BYTES


async def test_timeout_kills_entire_process_group(
    provider: LocalSandboxProvider, tmp_path: Path
) -> None:
    pid_file = tmp_path / "child.pid"
    command = f"sleep 30 & echo $! > {pid_file}; wait"

    with pytest.raises(SandboxUnavailable, match="timeout"):
        await provider.exec("agent-machine", command, timeout_s=0.1)

    child_pid = int(pid_file.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


async def test_timeout_kills_child_after_shell_exits(
    provider: LocalSandboxProvider, tmp_path: Path
) -> None:
    pid_file = tmp_path / "exited-shell-child.pid"

    with pytest.raises(SandboxUnavailable, match="timeout"):
        await asyncio.wait_for(
            provider.exec(
                "agent-machine", f"sleep 30 & echo $! > {pid_file}; exit 0", timeout_s=0.1
            ),
            timeout=1,
        )

    child_pid = int(pid_file.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert not [
        pending
        for pending in asyncio.all_tasks()
        if pending.get_name().startswith("local-sandbox-") and not pending.done()
    ]


async def test_cancellation_kills_process_group_and_reader_tasks(
    provider: LocalSandboxProvider, tmp_path: Path
) -> None:
    pid_file = tmp_path / "cancelled-child.pid"
    task = asyncio.create_task(
        provider.exec("agent-machine", f"sleep 30 & echo $! > {pid_file}; exit 0")
    )
    await asyncio.sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    child_pid = int(pid_file.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert not [
        pending
        for pending in asyncio.all_tasks()
        if pending.get_name().startswith("local-sandbox-") and not pending.done()
    ]


async def test_private_file_operations_are_atomic_and_do_not_expand_tilde(
    provider: LocalSandboxProvider, tmp_path: Path
) -> None:
    existing_parent = tmp_path / "private"
    existing_parent.mkdir(mode=0o755)
    os.chmod(existing_parent, 0o755)
    target = existing_parent / "nested" / "deeper" / "state.txt"

    old_umask = os.umask(0o022)
    try:
        await provider.write_file("agent-machine", str(target), "first")
    finally:
        os.umask(old_umask)

    await provider.write_file("agent-machine", str(target), "second")

    assert await provider.read_file("agent-machine", str(target)) == "second"
    assert await provider.read_file("agent-machine", str(tmp_path / "missing")) is None
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.parent.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(existing_parent.stat().st_mode) == 0o755
    with pytest.raises(ValueError, match="absolute"):
        await provider.read_file("agent-machine", "~/state.txt")
