import asyncio
import json
from pathlib import Path

import pytest
from harness_server.adapters.sandbox import ExecResult, FakeSandbox, JournalEntry
from harness_server.adapters.vault import VaultError
from harness_server.config import HarnessConfig
from harness_server.services import git_access
from harness_server.services.machine import (
    MachineError,
    _ensure_managed_directory,
    check_prerequisites,
    init_memory,
    init_project,
    sync_clone,
    write_mcp_config,
)
from pydantic import SecretStr


def config(memory: bool = False) -> HarnessConfig:
    sandbox: dict[str, object] = {"provider_id": "local"}
    if memory:
        sandbox["memory"] = {}
    return HarnessConfig.model_validate(
        {
            "workspaces": [
                {
                    "id": "demo",
                    "name": "Demo",
                    "voice_aliases": [],
                    "repo": {"provider": "github", "project": "owner/demo"},
                }
            ],
            "sandbox": sandbox,
        }
    )


@pytest.mark.asyncio
async def test_prerequisites_aggregate_and_node_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeSandbox("local")
    monkeypatch.setattr("harness_server.services.machine.shutil.which", lambda _: None)
    with pytest.raises(MachineError, match="git, node, npm, claude, openspec") as error:
        await check_prerequisites(provider, "local", False)
    assert error.value.code == 3
    monkeypatch.setattr("harness_server.services.machine.shutil.which", lambda _: "/bin/x")
    provider.respond("node --version", stdout="v22.13.0\n")
    provider.respond("git --version", stdout="2.45.0\n")
    provider.respond("npm --version", stdout="10.0.0\n")
    provider.respond("claude --version", stdout="1.0.0\n")
    provider.respond("openspec --version", stdout="1.0.0\n")
    await check_prerequisites(provider, "local", False)


@pytest.mark.asyncio
async def test_prerequisites_prints_only_safe_versions_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = FakeSandbox("local")
    monkeypatch.setattr("harness_server.services.machine.shutil.which", lambda _: "/bin/tool")
    provider.respond("node --version", stdout="v22.13.1 hostile-secret\n")
    provider.respond("git --version", stdout="git version 2.45.0\n")
    provider.respond("npm --version", stdout="10.8.0\n")
    provider.respond("claude --version", stdout="1.2.3\n")
    provider.respond("openspec --version", stdout="2.1.0\n")
    await check_prerequisites(provider, "local", False)
    output = capsys.readouterr().out
    assert "node v22.13.1" in output
    assert "hostile-secret" not in output


@pytest.mark.asyncio
async def test_prerequisites_reports_missing_tool_old_node_and_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeSandbox("local")
    monkeypatch.setattr(
        "harness_server.services.machine.shutil.which",
        lambda command: None if command == "git" else "/operator/bin/tool",
    )
    provider.respond("node --version", stdout="v22.12.9\n")
    provider.respond("npm --version", stdout="10.9.0\n")
    provider.respond("claude --version", stdout="1.0.0\n")
    provider.respond("openspec --version", stdout="2.0.0\n")

    with pytest.raises(MachineError) as error:
        await check_prerequisites(provider, "local", False)

    assert error.value.code == 3
    assert "git" in error.value.reason
    assert "node >= 22.13" in error.value.reason
    assert "node v22.12.9" in error.value.reason
    assert "npm 10.9.0" in error.value.reason


@pytest.mark.asyncio
async def test_prerequisites_require_running_docker_engine_for_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeSandbox("local")
    monkeypatch.setattr(
        "harness_server.services.machine.shutil.which", lambda _: "/operator/bin/tool"
    )
    provider.respond("node --version", stdout="v22.13.0\n")
    provider.respond("docker compose version", stdout="Docker Compose version v2.30.0\n")
    provider.respond("docker info", exit_code=1, stderr="daemon stopped")

    with pytest.raises(MachineError, match="docker engine") as error:
        await check_prerequisites(provider, "local", True)

    assert error.value.code == 3


@pytest.mark.asyncio
async def test_memory_marker_and_exclude_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    provider = FakeSandbox("local")
    workspace = config(True).workspaces[0]
    await init_memory(provider, "local", workspace, SecretStr("synthetic-embedding"))
    await init_memory(provider, "local", workspace, SecretStr("synthetic-embedding"))
    commands = [entry.cmd for entry in provider.journal if entry.method == "exec"]
    assert commands.count("memory init") == 1
    assert provider.received_env("EMBEDDING_API_KEY") == "synthetic-embedding"
    assert provider.files_containing("synthetic-embedding") == []


@pytest.mark.asyncio
async def test_init_memory_rejects_git_info_symlink_escape_before_read_or_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, outside = tmp_path / "home", tmp_path / "outside"
    repo = home / "work" / "demo"
    (repo / ".git").mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "exclude"
    sentinel.write_text("outside")
    (repo / ".git" / "info").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    provider = FakeSandbox("local")
    with pytest.raises(MachineError, match="вне HOME"):
        await init_memory(provider, "local", config(True).workspaces[0], None)
    assert sentinel.read_text() == "outside"
    assert not [entry for entry in provider.journal if entry.cmd == "memory init"]


@pytest.mark.asyncio
async def test_init_memory_rejects_memory_symlink_escape_before_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, outside = tmp_path / "home", tmp_path / "outside"
    repo = home / "work" / "demo"
    (repo / ".git" / "info").mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "keep"
    sentinel.write_text("outside")
    (repo / ".memory").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    provider = FakeSandbox("local")
    with pytest.raises(MachineError, match="вне HOME"):
        await init_memory(provider, "local", config(True).workspaces[0], None)
    assert sentinel.read_text() == "outside"
    assert not [entry for entry in provider.journal if entry.cmd == "memory init"]


@pytest.mark.asyncio
async def test_mcp_is_placeholder_only_and_clone_uses_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    provider = FakeSandbox("local")
    workspace = config().workspaces[0]
    await write_mcp_config(provider, "local")
    await sync_clone(provider, "local", workspace, SecretStr("synthetic-repo-key"))
    assert provider.files_containing("synthetic-repo-key") == []
    mcp_path = str(tmp_path / ".harness" / "mcp.json")
    mcp = json.loads((await provider.read_file("local", mcp_path)) or "{}")
    server = mcp["mcpServers"]["agents-flow"]
    assert server == {
        "type": "http",
        "url": "${AGENTS_FLOW_URL}",
        "headers": {"Authorization": "Bearer ${AGENTS_FLOW_TOKEN}"},
    }
    assert provider.received_env("GIT_CONFIG_VALUE_0") is not None


@pytest.mark.asyncio
async def test_non_repo_does_not_run_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "work" / "demo").mkdir(parents=True)
    provider = FakeSandbox("local")
    with pytest.raises(MachineError, match="не является"):
        await sync_clone(provider, "local", config().workspaces[0], None)
    assert provider.journal == []


@pytest.mark.asyncio
async def test_sync_clone_rejects_external_git_directory_before_any_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, outside = tmp_path / "home", tmp_path / "outside"
    repo = home / "work" / "demo"
    outside.mkdir()
    sentinel = outside / "config"
    sentinel.write_text("outside")
    repo.mkdir(parents=True)
    (repo / ".git").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    provider = FakeSandbox("local")

    with pytest.raises(MachineError, match="git metadata вне HOME"):
        await sync_clone(provider, "local", config().workspaces[0], None)

    assert sentinel.read_text() == "outside"
    assert provider.journal == []


@pytest.mark.asyncio
async def test_sync_clone_rejects_gitfile_before_any_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, outside = tmp_path / "home", tmp_path / "outside"
    repo = home / "work" / "demo"
    repo.mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "config"
    sentinel.write_text("outside")
    (repo / ".git").write_text(f"gitdir: {outside}\n")
    monkeypatch.setenv("HOME", str(home))
    provider = FakeSandbox("local")

    with pytest.raises(MachineError, match="git metadata вне HOME"):
        await sync_clone(provider, "local", config().workspaces[0], None)

    assert sentinel.read_text() == "outside"
    assert provider.journal == []


@pytest.mark.asyncio
async def test_sync_clone_rejects_real_repo_config_symlink_before_any_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, outside = tmp_path / "home", tmp_path / "outside"
    repo = home / "work" / "demo"
    outside.mkdir()
    sentinel = outside / "config"
    sentinel.write_text("outside")
    process = await asyncio.create_subprocess_exec("git", "init", "-q", str(repo))
    assert await process.wait() == 0
    (repo / ".git" / "config").unlink()
    (repo / ".git" / "config").symlink_to(sentinel)
    monkeypatch.setenv("HOME", str(home))
    provider = FakeSandbox("local")

    with pytest.raises(MachineError, match="git metadata вне HOME"):
        await sync_clone(provider, "local", config().workspaces[0], SecretStr("synthetic-repo-key"))

    assert sentinel.read_text() == "outside"
    assert provider.journal == []


@pytest.mark.asyncio
async def test_sync_clone_rejects_real_repo_objects_symlink_before_any_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, outside = tmp_path / "home", tmp_path / "outside"
    repo = home / "work" / "demo"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("outside")
    process = await asyncio.create_subprocess_exec("git", "init", "-q", str(repo))
    assert await process.wait() == 0
    objects = repo / ".git" / "objects"
    for child in objects.iterdir():
        child.rmdir()
    objects.rmdir()
    objects.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    provider = FakeSandbox("local")

    with pytest.raises(MachineError, match="git metadata вне HOME"):
        await sync_clone(provider, "local", config().workspaces[0], None)

    assert sentinel.read_text() == "outside"
    assert list(outside.iterdir()) == [sentinel]
    assert provider.journal == []


@pytest.mark.asyncio
async def test_sync_clone_existing_repo_restores_origin_before_fetch_with_env_only_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "work" / "demo"
    (repo / ".git" / "refs").mkdir(parents=True)
    (repo / ".git" / "logs").mkdir()
    (repo / ".git" / "config").write_text("[core]\nrepositoryformatversion = 0\n")
    provider = FakeSandbox("local")
    workspace = config().workspaces[0]
    key = "synthetic-repo-key"

    await sync_clone(provider, "local", workspace, SecretStr(key))

    commands = [entry.cmd or "" for entry in provider.journal]
    remote = commands.index(git_access.set_origin_command(workspace.repo, str(repo)))
    fetch = commands.index(git_access.fetch_command(workspace.repo, str(repo)))
    assert remote < fetch
    assert provider.received_env("GIT_CONFIG_VALUE_0") is not None
    assert all(key not in command for command in commands)
    assert provider.files_containing(key) == []


@pytest.mark.asyncio
async def test_anonymous_clone_warns_to_stderr_without_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    await sync_clone(FakeSandbox("local"), "local", config().workspaces[0], None)

    assert capsys.readouterr().err == "workspace demo: нет repo.access_ref, клон анонимный\n"


@pytest.mark.asyncio
async def test_init_project_redacts_secret_from_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_marker = "synthetic-secret-marker"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("harness_server.services.machine.require_non_root", lambda: None)

    async def prerequisites(*_: object) -> None:
        return None

    async def resolve_fake(*_: object, **__: object) -> SecretStr:
        return SecretStr(secret_marker)

    monkeypatch.setattr("harness_server.services.machine.check_prerequisites", prerequisites)
    monkeypatch.setattr("harness_server.services.machine.secret_refs.resolve", resolve_fake)
    cfg = config()
    cfg.workspaces[0].id = secret_marker

    await init_project(cfg, secret_marker, None, provider=FakeSandbox("local"))

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert secret_marker not in output
    assert "[REDACTED]" in output


@pytest.mark.asyncio
async def test_init_rejects_harness_symlink_escape_before_outside_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, outside = tmp_path / "home", tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    (home / ".harness").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("harness_server.services.machine.require_non_root", lambda: None)

    async def no_prerequisites(*_: object) -> None:
        return None

    monkeypatch.setattr("harness_server.services.machine.check_prerequisites", no_prerequisites)
    with pytest.raises(MachineError, match="вне HOME"):
        await init_project(config(), "demo", None)

    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_init_does_not_unlink_ready_marker_through_projects_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, outside = tmp_path / "home", tmp_path / "outside"
    home.mkdir()
    (home / ".harness").mkdir()
    outside.mkdir()
    ready = outside / "demo.ready"
    ready.write_text("keep")
    (home / ".harness" / "projects").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("harness_server.services.machine.require_non_root", lambda: None)

    async def no_prerequisites(*_: object) -> None:
        return None

    monkeypatch.setattr("harness_server.services.machine.check_prerequisites", no_prerequisites)
    with pytest.raises(MachineError, match="вне HOME"):
        await init_project(config(), "demo", None)
    assert ready.read_text() == "keep"


@pytest.mark.asyncio
async def test_init_project_orders_ready_after_clone_and_mcp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("harness_server.services.machine.require_non_root", lambda: None)

    async def prerequisites(*_: object) -> None:
        return None

    monkeypatch.setattr("harness_server.services.machine.check_prerequisites", prerequisites)
    provider = FakeSandbox("local")
    await init_project(config(), "demo", None, provider=provider)

    journal = provider.journal
    clone = next(
        index for index, entry in enumerate(journal) if entry.cmd and "git clone" in entry.cmd
    )
    mcp = next(
        index for index, entry in enumerate(journal) if entry.cmd and entry.cmd.endswith("mcp.json")
    )
    ready = next(
        index
        for index, entry in enumerate(journal)
        if entry.cmd and entry.cmd.endswith("demo.ready")
    )
    assert clone < mcp < ready
    assert await provider.read_file("local", str(tmp_path / ".harness" / "projects" / "demo.ready"))


@pytest.mark.asyncio
async def test_init_project_failure_never_writes_ready_and_vault_precedes_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("harness_server.services.machine.require_non_root", lambda: None)

    async def prerequisites(*_: object) -> None:
        return None

    monkeypatch.setattr("harness_server.services.machine.check_prerequisites", prerequisites)
    provider = FakeSandbox("local")
    provider.respond("git clone", exit_code=1, stderr="secret-value")
    with pytest.raises(MachineError, match="git"):
        await init_project(config(), "demo", None, provider=provider)
    ready_path = str(tmp_path / ".harness" / "projects" / "demo.ready")
    assert await provider.read_file("local", ready_path) is None

    class _FailingVault:
        async def get(self, _ref: object) -> SecretStr:
            raise VaultError("unavailable")

    secured = config()
    secured.workspaces[0].repo.access_ref = "vault:demo/git/token"
    vault_home = tmp_path / "vault-home"
    monkeypatch.setenv("HOME", str(vault_home))
    with pytest.raises(MachineError, match="vault"):
        await init_project(secured, "demo", _FailingVault(), provider=FakeSandbox("local"))
    assert not (vault_home / ".harness").exists()


@pytest.mark.asyncio
async def test_init_project_repeat_removes_stale_ready_and_fetches_without_reclone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StatefulProvider(FakeSandbox):
        repo_exists = False
        fail_fetch = False

        async def exec(
            self,
            sandbox_id: str,
            cmd: str,
            *,
            envs: dict[str, str] | None = None,
            cwd: str | None = None,
            timeout_s: float = 60,
        ) -> ExecResult:
            if cmd.startswith("if [ -d"):
                return ExecResult(0, "repo\n" if self.repo_exists else "absent\n", "")
            if cmd.startswith("git clone"):
                self.repo_exists = True
            if self.fail_fetch and cmd.startswith("git") and "fetch" in cmd:
                self.journal.append(JournalEntry("exec", cmd, tuple(sorted(envs or {})), cwd))
                return ExecResult(1, "", "synthetic-repeat-secret")
            return await super().exec(sandbox_id, cmd, envs=envs, cwd=cwd, timeout_s=timeout_s)

        async def write_file(self, sandbox_id: str, path: str, data: str) -> None:
            await super().write_file(sandbox_id, path, data)
            if path.endswith(".ready"):
                target = Path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                # The tiny fixture write must not depend on an executor worker, which can stall
                # indefinitely in this async test environment.
                target.write_text(data)  # noqa: ASYNC240

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("harness_server.services.machine.require_non_root", lambda: None)

    async def prerequisites(*_: object) -> None:
        return None

    monkeypatch.setattr("harness_server.services.machine.check_prerequisites", prerequisites)
    provider = StatefulProvider("local")
    await init_project(config(), "demo", None, provider=provider)
    marker = tmp_path / ".harness" / "projects" / "demo.ready"
    assert marker.read_text() == "ready\n"
    (tmp_path / "work" / "demo" / ".git").mkdir(parents=True)
    provider.fail_fetch = True

    with pytest.raises(MachineError, match="git") as error:
        await init_project(config(), "demo", None, provider=provider)

    commands = [entry.cmd or "" for entry in provider.journal]
    clone_command = next(command for command in commands if command.startswith("git clone"))
    assert commands.count(clone_command) == 1
    assert any(" remote set-url " in command for command in commands)
    assert any(" fetch " in command for command in commands)
    assert not marker.exists()
    assert "synthetic-repeat-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_init_project_memory_enabled_uses_embedding_only_in_command_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Vault:
        async def get(self, _ref: object) -> SecretStr:
            return SecretStr("synthetic-embedding-secret")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("harness_server.services.machine.require_non_root", lambda: None)

    async def prerequisites(*_: object) -> None:
        return None

    monkeypatch.setattr("harness_server.services.machine.check_prerequisites", prerequisites)
    configured = config(True)
    assert configured.sandbox.memory is not None
    configured.sandbox.memory.embedding_ref = "vault:demo/memory/key"
    provider = FakeSandbox("local")
    await init_project(configured, "demo", Vault(), provider=provider)

    assert any(entry.cmd == "memory init" for entry in provider.journal)
    assert provider.received_env("EMBEDDING_API_KEY") == "synthetic-embedding-secret"
    assert provider.files_containing("synthetic-embedding-secret") == []
    assert await provider.read_file("local", str(tmp_path / ".harness" / "memory" / "demo.ready"))


def test_existing_managed_directory_is_repaired_to_private_mode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    managed = home / ".harness" / "projects"
    managed.mkdir(parents=True)
    managed.chmod(0o755)
    _ensure_managed_directory(managed, home.resolve())
    assert managed.stat().st_mode & 0o777 == 0o700
