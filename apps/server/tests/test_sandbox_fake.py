"""Минимальные тесты FakeSandbox: журнал без значений env, файлы, ответы exec, удаление."""

import pytest
from harness_server.adapters.sandbox import FakeSandbox, SandboxNotFound

pytestmark = pytest.mark.asyncio

TOKEN = "oauth-token-value-0123456789"


async def test_journal_records_env_keys_not_values() -> None:
    sandbox = FakeSandbox()

    await sandbox.exec(sandbox.sandbox_id, "claude -p x", envs={"CLAUDE_CODE_OAUTH_TOKEN": TOKEN})

    assert sandbox.journal[-1].env_keys == ("CLAUDE_CODE_OAUTH_TOKEN",)
    assert TOKEN not in repr(sandbox.journal)
    assert sandbox.received_env("CLAUDE_CODE_OAUTH_TOKEN") == TOKEN


async def test_files_roundtrip_and_missing_file_is_none() -> None:
    sandbox = FakeSandbox()

    await sandbox.write_file(sandbox.sandbox_id, "/home/u/a.txt", "hello")

    assert await sandbox.read_file(sandbox.sandbox_id, "/home/u/a.txt") == "hello"
    assert await sandbox.read_file(sandbox.sandbox_id, "/home/u/missing") is None
    assert sandbox.files_containing("hell") == ["/home/u/a.txt"]


async def test_programmed_response_uses_longest_prefix() -> None:
    sandbox = FakeSandbox()
    sandbox.respond("git", stdout="generic")
    sandbox.respond("git worktree", exit_code=128, stderr="fatal")

    generic = await sandbox.exec(sandbox.sandbox_id, "git status")
    specific = await sandbox.exec(sandbox.sandbox_id, "git worktree add x")

    assert generic.stdout == "generic"
    assert specific.exit_code == 128


async def test_pause_and_connect_toggle_flag() -> None:
    sandbox = FakeSandbox()

    await sandbox.pause(sandbox.sandbox_id)
    assert sandbox.paused is True

    await sandbox.connect(sandbox.sandbox_id)
    assert sandbox.paused is False


async def test_killed_or_foreign_sandbox_is_not_found() -> None:
    sandbox = FakeSandbox()

    with pytest.raises(SandboxNotFound):
        await sandbox.exec("other-id", "ls")

    sandbox.kill()
    with pytest.raises(SandboxNotFound):
        await sandbox.exec(sandbox.sandbox_id, "ls")
