"""Механическая проверка закоммиченного изменения OpenSpec."""

import re
import shlex

from harness_shared.planning import PlanState
from harness_shared.tasks import TaskStatus

from harness_server.adapters.sandbox import SandboxProvider


async def validate_plan(
    provider: SandboxProvider,
    sandbox_id: str,
    worktree: str,
    base_ref: str,
    branch: str,
    state: PlanState,
) -> str | None:
    """Возвращает только безопасный код; stdout OpenSpec не попадает в отчёт."""
    git = ["git", "-C", worktree]
    current = await provider.exec(sandbox_id, shlex.join([*git, "branch", "--show-current"]))
    if current.exit_code or current.stdout.strip() != branch:
        return "plan_branch"
    dirty = await provider.exec(
        sandbox_id,
        shlex.join(
            [
                *git,
                "status",
                "--porcelain",
                "--untracked-files=all",
            ]
        ),
    )
    if dirty.exit_code or dirty.stdout.strip():
        return "plan_uncommitted"
    trees: list[set[str]] = []
    marker = "\nHARNESS_TREE_COMPLETE\n"
    for ref in (base_ref, "HEAD"):
        result = await provider.exec(
            sandbox_id,
            shlex.join(
                [
                    *git,
                    "ls-tree",
                    "-r",
                    "--name-only",
                    "-z",
                    ref,
                    "--",
                    "openspec/changes/",
                ]
            )
            + " && printf '\\nHARNESS_TREE_COMPLETE\\n'",
        )
        if result.exit_code or not result.stdout.endswith(marker):
            return "plan_tree"
        trees.append(set(filter(None, result.stdout.removesuffix(marker).split("\0"))))
    base, head = trees

    def changes(paths: set[str]) -> set[str]:
        return {path.split("/")[2] for path in paths if len(path.split("/")) >= 4}

    new = changes(head) - changes(base)
    if len(new) != 1:
        return "plan_new_change"
    change_id = next(iter(new))
    if re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", change_id) is None:
        return "plan_change_id"
    prefix = f"openspec/changes/{change_id}/"
    if not all(prefix + name in head for name in ("proposal.md", "design.md", "tasks.md")):
        return "plan_artifacts"
    if not any(path.startswith(prefix + "specs/") and path.endswith("/spec.md") for path in head):
        return "plan_artifacts"
    items = {item.id: item for item in state.items}
    if not state.children or any(
        child.status != TaskStatus.BACKLOG
        or child.spec_item_id not in items
        or items[child.spec_item_id].change_id != change_id
        or items[child.spec_item_id].plan_task_id != child.parent_id
        for child in state.children
    ):
        return "plan_no_implementations"
    result = await provider.exec(
        sandbox_id,
        shlex.join(["openspec", "validate", change_id]),
        cwd=worktree,
    )
    return None if result.exit_code == 0 else "plan_invalid_spec"
