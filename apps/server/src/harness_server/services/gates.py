"""Проверка секретов и идемпотентная публикация ветки через провайдер песочницы."""

import re
import shlex
from collections.abc import Iterable
from dataclasses import dataclass

from harness_shared.projects import ProjectRepo
from pydantic import SecretStr

from harness_server.adapters.sandbox import SandboxProvider
from harness_server.security.redaction import scan_diff
from harness_server.services import git_access

_DIFF_END = "\nHARNESS_DIFF_COMPLETE\n"


@dataclass(frozen=True, slots=True)
class GateResult:
    """Итог гейта без вывода git и значений секретов."""

    ok: bool
    reason: str | None = None
    skipped: bool = False


async def secret_scan(
    provider: SandboxProvider,
    sandbox_id: str,
    worktree: str,
    base_ref: str,
    extra_values: Iterable[str] = (),
) -> GateResult:
    """Проверяет весь diff относительно базы; ошибка git закрывает гейт."""
    command = shlex.join(
        [
            "git",
            "-C",
            worktree,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            f"{base_ref}...HEAD",
            "--",
        ]
    )
    # exec ограничивает stdout: отсутствие завершающего маркера закрывает гейт при усечении.
    result = await provider.exec(sandbox_id, command + " && printf '\\nHARNESS_DIFF_COMPLETE\\n'")
    if result.exit_code:
        return GateResult(False, "secret_scan_diff_failed")
    if not result.stdout.endswith(_DIFF_END):
        return GateResult(False, "secret_scan_diff_incomplete")
    if scan_diff(result.stdout.removesuffix(_DIFF_END), extra_values):
        return GateResult(False, "secret_scan_found")
    return GateResult(True)


async def push(
    provider: SandboxProvider,
    sandbox_id: str,
    worktree: str,
    branch: str,
    repo: ProjectRepo,
    token: SecretStr,
) -> GateResult:
    """Сравнивает удалённый ref с HEAD и пушит зафиксированный хеш без force и MR.

    Адрес и авторизация берутся из настроек workspace: изменённый агентом origin не
    получает ключ. Вывод git не включается в причины отказа.
    """
    if not branch.startswith("task/"):
        return GateResult(False, "push_ref_failed")
    envs = git_access.git_auth_env(repo, token.get_secret_value())
    git = ["git", "-C", worktree]
    head = await provider.exec(sandbox_id, shlex.join([*git, "rev-parse", "--verify", "HEAD"]))
    commit = head.stdout.strip()
    if head.exit_code or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None:
        return GateResult(False, "push_head_failed")
    ref = f"refs/heads/{branch}"
    checked = await provider.exec(sandbox_id, shlex.join([*git, "check-ref-format", ref]))
    if checked.exit_code:
        return GateResult(False, "push_ref_failed")
    remote = await provider.exec(
        sandbox_id,
        shlex.join([*git, "ls-remote", "--refs", git_access.clone_url(repo), ref]),
        envs=envs,
    )
    if remote.exit_code:
        return GateResult(False, "push_remote_failed")
    if any(line.split() == [commit, ref] for line in remote.stdout.splitlines()):
        return GateResult(True, skipped=True)
    result = await provider.exec(
        sandbox_id,
        shlex.join([*git, "push", "--no-verify", git_access.clone_url(repo), f"{commit}:{ref}"]),
        envs=envs,
    )
    return GateResult(True) if result.exit_code == 0 else GateResult(False, "push_failed")
