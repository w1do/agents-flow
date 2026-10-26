"""Idempotent, host-local project preparation behind the ``agent`` CLI."""

import os
import re
import shutil
import stat
import sys
from pathlib import Path

import yaml
from harness_shared.projects import Workspace
from pydantic import SecretStr

from harness_server.adapters.sandbox import SandboxProvider
from harness_server.adapters.vault import SecretVault, VaultError
from harness_server.config import HarnessConfig
from harness_server.security.redaction import redact
from harness_server.services import git_access
from harness_server.services import secrets as secret_refs

AGENT_CLIENT_COMMAND = "claude"
# Первичная индексация с эмбеддингами длится минуты; общий таймаут exec (60 с) её обрывает.
MEMORY_INIT_TIMEOUT_S = 1800


class RootUserError(Exception):
    """Машина агента запущена от root вместо отдельного пользователя."""


def require_non_root(*, uid: int | None = None) -> None:
    """Отказывает root до любых изменений файлов машины или запуска дочерних процессов."""
    if (os.geteuid() if uid is None else uid) == 0:
        raise RootUserError("нужен отдельный пользователь без root")


class MachineError(Exception):
    def __init__(self, code: int, reason: str) -> None:
        self.code, self.reason = code, reason
        super().__init__(reason)


def _home() -> Path:
    return Path(os.environ["HOME"]).resolve()


async def check_prerequisites(provider: SandboxProvider, sandbox_id: str, memory: bool) -> None:
    """Report all missing owner-installed tools before writing anything."""
    missing: list[str] = []
    versions: list[str] = []
    commands = ("git", "node", "npm", AGENT_CLIENT_COMMAND, "openspec")
    for command in commands:
        if shutil.which(command) is None:
            missing.append(command)
            continue
        result = await provider.exec(sandbox_id, f"{command} --version")
        if result.exit_code:
            missing.append(command)
        else:
            version = _safe_version(result.stdout)
            if version is None:
                missing.append(command)
                continue
            versions.append(f"{command} {version}")
            if command == "node":
                match = re.match(r"v?(\d+)\.(\d+)", version)
                if match is None or tuple(map(int, match.groups())) < (22, 13):
                    missing.append("node >= 22.13")
    if memory:
        if shutil.which("memory") is None:
            missing.append("memory")
        else:
            result = await provider.exec(sandbox_id, "memory --version")
            if result.exit_code:
                missing.append("memory")
            else:
                version = _safe_version(result.stdout)
                if version is None:
                    missing.append("memory")
                else:
                    versions.append(f"memory {version}")
        result = await provider.exec(sandbox_id, "docker compose version")
        if result.exit_code:
            missing.append("docker compose")
        else:
            version = _safe_version(result.stdout)
            if version is None:
                missing.append("docker compose")
            else:
                versions.append(f"docker compose {version}")
            engine = await provider.exec(sandbox_id, "docker info")
            if engine.exit_code:
                missing.append("docker engine")
    if missing:
        details = "; ".join(versions)
        reason = "нет " + ", ".join(missing)
        raise MachineError(3, reason + (f"; найдено: {details}" if details else ""))
    print(redact("найдено: " + "; ".join(versions)))


def _safe_version(output: str) -> str | None:
    """Return only a conventional version token, never arbitrary tool output."""
    match = re.search(r"\bv?\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?\b", output)
    return match.group(0) if match else None


def _ensure_managed_directory(path: Path, home: Path) -> None:
    """Create only missing directories in the machine-owned hierarchy.

    Resolving the existing ancestor before mutation prevents ``.harness`` or
    ``work`` symlinks from redirecting a setup run outside the actual HOME.
    """
    if not path.is_relative_to(home):
        raise MachineError(1, "путь машины вне HOME")
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if not cursor.resolve().is_relative_to(home):
        raise MachineError(1, "путь машины вне HOME")
    if not missing and path.exists():
        os.chmod(path, 0o700)
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)


def _assert_inside_home(path: Path, home: Path) -> None:
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        raise MachineError(1, "путь машины вне HOME") from None
    if not path.is_relative_to(home) or not resolved.is_relative_to(home):
        raise MachineError(1, "путь машины вне HOME")


def _assert_git_metadata_inside_home(git_dir: Path, home: Path) -> None:
    """Reject every symlink or non-regular entry below metadata git may mutate.

    Fetch can create objects, refs, reflogs, indexes and pack files, so checking a hand-picked
    subset leaves a writable escape.  A linked-worktree common-dir is external metadata too.
    """
    if (git_dir / "commondir").exists() or (git_dir / "commondir").is_symlink():
        raise MachineError(1, "git metadata вне HOME")
    pending = [git_dir]
    while pending:
        directory = pending.pop()
        try:
            _assert_inside_home(directory, home)
            with os.scandir(directory) as entries:
                children = list(entries)
        except (MachineError, OSError):
            raise MachineError(1, "git metadata вне HOME") from None
        for entry in children:
            path = Path(entry.path)
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
                _assert_inside_home(path, home)
            except (MachineError, OSError):
                raise MachineError(1, "git metadata вне HOME") from None
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise MachineError(1, "git metadata вне HOME")
            if stat.S_ISDIR(mode):
                pending.append(path)


async def write_mcp_config(provider: SandboxProvider, sandbox_id: str) -> None:
    await provider.write_file(
        sandbox_id,
        str(_home() / ".harness" / "mcp.json"),
        '{"mcpServers":{"agents-flow":{"type":"http","url":"${AGENTS_FLOW_URL}",'
        '"headers":{"Authorization":"Bearer ${AGENTS_FLOW_TOKEN}"}}}}\n',
    )


async def sync_clone(
    provider: SandboxProvider,
    sandbox_id: str,
    workspace: Workspace,
    token: SecretStr | None,
) -> None:
    repo_dir = _home() / "work" / workspace.id
    home = _home()
    _assert_inside_home(repo_dir, home)
    git_dir = repo_dir / ".git"
    if repo_dir.exists():
        if not git_dir.is_dir():
            # A gitfile may point its metadata to any path.  Do not read it or let git resolve it:
            # agent-init owns only ordinary metadata below HOME.
            if git_dir.exists() or git_dir.is_symlink():
                raise MachineError(1, "git metadata вне HOME")
            raise MachineError(1, f"{repo_dir} не является git-репозиторием")
        _assert_git_metadata_inside_home(git_dir, home)
    env = (
        git_access.git_auth_env(workspace.repo, token.get_secret_value())
        if token
        else git_access.anonymous_git_env()
    )
    if workspace.repo.access_ref is None:
        print(
            redact(
                f"workspace {workspace.id}: нет repo.access_ref, клон анонимный",
                extra_values=(token.get_secret_value(),) if token is not None else (),
            ),
            file=sys.stderr,
        )
    if repo_dir.exists():
        for command in (
            git_access.set_origin_command(workspace.repo, str(repo_dir)),
            git_access.fetch_command(workspace.repo, str(repo_dir)),
        ):
            result = await provider.exec(sandbox_id, command, envs=env)
            if result.exit_code:
                raise MachineError(1, "git")
    else:
        result = await provider.exec(
            sandbox_id, git_access.clone_command(workspace.repo, str(repo_dir)), envs=env
        )
        if result.exit_code:
            raise MachineError(1, "git")


async def init_memory(
    provider: SandboxProvider,
    sandbox_id: str,
    workspace: Workspace,
    embedding: SecretStr | None,
) -> None:
    repo = _home() / "work" / workspace.id
    home = _home()
    _assert_inside_home(repo, home)
    git_dir = repo / ".git"
    # A gitfile points metadata elsewhere; agent-init owns only ordinary metadata
    # below its workspace and must not edit a linked worktree's gitdir.
    if git_dir.exists() and not git_dir.is_dir():
        raise MachineError(1, "git metadata вне HOME")
    _assert_inside_home(git_dir, home)
    info_dir = git_dir / "info"
    exclude = repo / ".git" / "info" / "exclude"
    memory_dir = repo / ".memory"
    for destination in (info_dir, exclude, memory_dir):
        _assert_inside_home(destination, home)
    old = await provider.read_file(sandbox_id, str(exclude)) or ""
    if ".memory/" not in old.splitlines():
        await provider.write_file(
            sandbox_id,
            str(exclude),
            old + ("" if old.endswith("\n") or not old else "\n") + ".memory/\n",
        )
    marker = _home() / ".harness" / "memory" / f"{workspace.id}.ready"
    if await provider.read_file(sandbox_id, str(marker)) is None:
        result = await provider.exec(
            sandbox_id,
            "memory init",
            cwd=str(repo),
            envs=(
                {"EMBEDDING_API_KEY": embedding.get_secret_value()} if embedding is not None else {}
            ),
            timeout_s=MEMORY_INIT_TIMEOUT_S,
        )
        if result.exit_code:
            raise MachineError(1, "memory")
        await provider.write_file(sandbox_id, str(marker), "ready\n")


def write_project_config(workspace: Workspace, *, home: Path | None = None) -> Path:
    """Пишет локальный конфиг проекта из серверной записи: ~/.harness/projects/<id>.yaml (0600).

    Файл генерируется целиком и помечен как сгенерированный: правки руками перезаписываются при
    следующем `agent init`. Значения ключей сюда не попадают: access_ref — только ссылка vault.
    """
    base = _home() if home is None else home
    root = base / ".harness"
    directory = root / "projects"
    _assert_inside_home(directory, base)
    for path in (root, directory):
        _ensure_managed_directory(path, base)
    target = directory / f"{workspace.id}.yaml"
    _assert_inside_home(target, base)
    body = yaml.safe_dump(
        {"workspace": workspace.model_dump(mode="json")},
        allow_unicode=True,
        sort_keys=False,
    )
    text = (
        "# Сгенерировано agent init из записи проекта на сервере. НЕ РЕДАКТИРОВАТЬ:\n"
        "# файл перезаписывается при следующем `agent init`. Источник — сервер (project-catalog).\n"
        f"{body}"
    )
    if target.is_symlink():
        raise MachineError(1, "локальный конфиг проекта — симлинк")
    # Права задаём при создании и явно на существующем файле: 0600 не зависит от umask.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)
    return target


async def init_project(
    config: HarnessConfig,
    workspace: Workspace,
    vault: SecretVault | None,
    *,
    provider: SandboxProvider | None = None,
) -> None:
    """Prepare exactly one project from its server record; readiness appears only at the end."""
    try:
        require_non_root()
    except RootUserError:
        raise MachineError(1, "нужен отдельный пользователь без root") from None
    if provider is None:
        # Импорт после root-проверки разрывает зависимость: LocalSandboxProvider использует её же.
        from harness_server.adapters.local import LocalSandboxProvider

        provider = LocalSandboxProvider(config.sandbox.provider_id)
    await check_prerequisites(
        provider, config.sandbox.provider_id, config.sandbox.memory is not None
    )
    try:
        token = await secret_refs.resolve(vault, workspace.repo.access_ref, fallback=None)
        embedding = await secret_refs.resolve(
            vault,
            config.sandbox.memory.embedding_ref if config.sandbox.memory else None,
            fallback=None,
        )
    except VaultError:
        raise MachineError(1, "vault") from None
    home = _home()
    root = home / ".harness"
    marker = root / "projects" / f"{workspace.id}.ready"
    directories = (
        root,
        root / "bin",
        root / "tasks",
        root / "worktrees",
        root / "projects",
        root / "memory",
        home / "work",
    )
    # Validate the entire owned hierarchy before touching the old marker.  In
    # particular, a symlinked projects directory must not redirect unlink().
    for directory in directories:
        _assert_inside_home(directory, home)
    _assert_inside_home(marker, home)
    if marker.exists():
        marker.unlink()
    for directory in directories:
        _ensure_managed_directory(directory, home)
    await sync_clone(provider, config.sandbox.provider_id, workspace, token)
    await write_mcp_config(provider, config.sandbox.provider_id)
    if config.sandbox.memory:
        await init_memory(provider, config.sandbox.provider_id, workspace, embedding)
    await provider.write_file(config.sandbox.provider_id, str(marker), "ready\n")
