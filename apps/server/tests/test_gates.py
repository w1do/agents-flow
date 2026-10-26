"""Гейты fail closed, повтор публикации пропускается, ключи не попадают в команды."""

import pytest
from harness_server.adapters.sandbox import FakeSandbox
from harness_server.services.git_access import git_auth_env
from harness_server.worker.gates import GateResult, push, secret_scan
from harness_shared.projects import ProjectRepo
from pydantic import SecretStr

WORKTREE = "/home/agent/worktree"
GIT = f"git -C {WORKTREE}"
COMMIT = "a" * 40
REPO = ProjectRepo(provider="gitlab", project="group/project")
TOKEN = SecretStr("test-repo-write-key")
DIFF_END = "\nHARNESS_DIFF_COMPLETE\n"


@pytest.mark.parametrize("secret", ["glpat-" + "a" * 24, "opaque-issued-key"])
async def test_secret_scan_blocks_patterns_and_issued_values(secret: str) -> None:
    sandbox = FakeSandbox()
    sandbox.respond(f"{GIT} diff", stdout=f"+key={secret}{DIFF_END}")
    result = await secret_scan(
        sandbox, sandbox.sandbox_id, WORKTREE, "origin/main", ["opaque-issued-key"]
    )
    assert result == GateResult(False, "secret_scan_found")
    assert secret not in repr(result)
    assert "origin/main...HEAD" in (sandbox.journal[0].cmd or "")


async def test_clean_diff_passes() -> None:
    sandbox = FakeSandbox()
    sandbox.respond(f"{GIT} diff", stdout=f"+описание плана{DIFF_END}")
    assert (await secret_scan(sandbox, sandbox.sandbox_id, WORKTREE, "origin/main")).ok


async def test_diff_failure_blocks_scan_without_exposing_output() -> None:
    sandbox = FakeSandbox()
    sandbox.respond(f"{GIT} diff", exit_code=1, stderr=TOKEN.get_secret_value())
    assert await secret_scan(sandbox, sandbox.sandbox_id, WORKTREE, "origin/main") == (
        GateResult(False, "secret_scan_diff_failed")
    )


async def test_push_is_skipped_on_second_run() -> None:
    sandbox = FakeSandbox()
    sandbox.respond(f"{GIT} rev-parse", stdout=COMMIT)
    first = await push(sandbox, sandbox.sandbox_id, WORKTREE, "task/plan", REPO, TOKEN)
    assert first == GateResult(True)
    sandbox.respond(f"{GIT} ls-remote", stdout=f"{COMMIT}\trefs/heads/task/plan\n")
    second = await push(sandbox, sandbox.sandbox_id, WORKTREE, "task/plan", REPO, TOKEN)
    assert second == GateResult(True, skipped=True)
    commands = [entry.cmd or "" for entry in sandbox.journal]
    pushes = [cmd for cmd in commands if " push " in cmd]
    assert len(pushes) == 1
    assert "https://gitlab.com/group/project.git" in pushes[0]
    assert f"{COMMIT}:refs/heads/task/plan" in pushes[0]
    assert TOKEN.get_secret_value() not in repr(sandbox.journal)
    for key, value in git_auth_env(REPO, TOKEN.get_secret_value()).items():
        assert sandbox.received_env(key) == value


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("rev-parse", "push_head_failed"),
        ("check-ref-format", "push_ref_failed"),
        ("ls-remote", "push_remote_failed"),
        ("push", "push_failed"),
    ],
)
async def test_git_failure_blocks_push_without_secret_output(command: str, reason: str) -> None:
    sandbox = FakeSandbox()
    if command != "rev-parse":
        sandbox.respond(f"{GIT} rev-parse", stdout=COMMIT)
    sandbox.respond(f"{GIT} {command}", exit_code=1, stderr=TOKEN.get_secret_value())
    assert await push(sandbox, sandbox.sandbox_id, WORKTREE, "task/plan", REPO, TOKEN) == (
        GateResult(False, reason)
    )
    if command != "push":
        assert not any(" push " in (entry.cmd or "") for entry in sandbox.journal)


async def test_matching_hash_for_another_branch_does_not_skip_push() -> None:
    sandbox = FakeSandbox()
    sandbox.respond(f"{GIT} rev-parse", stdout=COMMIT)
    sandbox.respond(f"{GIT} ls-remote", stdout=f"{COMMIT}\trefs/heads/task/other\n")
    assert await push(sandbox, sandbox.sandbox_id, WORKTREE, "task/plan", REPO, TOKEN) == (
        GateResult(True)
    )


async def test_push_to_default_branch_is_rejected_before_git() -> None:
    sandbox = FakeSandbox()
    assert await push(sandbox, sandbox.sandbox_id, WORKTREE, "main", REPO, TOKEN) == (
        GateResult(False, "push_ref_failed")
    )
    assert sandbox.journal == []


async def test_truncated_diff_blocks_scan() -> None:
    sandbox = FakeSandbox()
    sandbox.respond(f"{GIT} diff", stdout="+начало большого diff")
    assert await secret_scan(sandbox, sandbox.sandbox_id, WORKTREE, "origin/main") == (
        GateResult(False, "secret_scan_diff_incomplete")
    )
