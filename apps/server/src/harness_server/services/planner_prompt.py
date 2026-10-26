"""Сборка промпта планировщика из безопасных сведений задачи и workspace."""

import json
from collections.abc import Iterable
from importlib import resources

from harness_shared.projects import Workspace
from harness_shared.tasks import TaskOut

from harness_server.security.redaction import redact


def build_planner_prompt(
    task: TaskOut, workspace: Workspace, extra_values: Iterable[str] = ()
) -> str:
    """Добавляет контекст без конфигурации ключей и очищает текст до передачи агенту."""
    values = tuple(extra_values)
    context = {
        "task_id": str(task.id),
        # До JSON: кавычки и переносы в значении ключа иначе изменятся при экранировании.
        "text": redact(task.text, values),
        "workspace": {"id": workspace.id, "name": redact(workspace.name, values)},
        "base_ref": redact(f"origin/{workspace.default_branch}", values),
        "branch": f"task/{task.id}",
    }
    template = (
        resources.files("harness_server.services.prompts")
        .joinpath("planner.md")
        .read_text(encoding="utf-8")
    )
    return redact(
        template.replace("<<PLAN_CONTEXT>>", json.dumps(context, ensure_ascii=False, indent=2)),
        values,
    )
