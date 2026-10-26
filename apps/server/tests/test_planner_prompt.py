"""Снимок промпта и отсутствие значений ключей в контексте планировщика."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from harness_server.services.planner_prompt import build_planner_prompt
from harness_shared.projects import ProjectRepo, Workspace
from harness_shared.tasks import TaskKind, TaskOut, TaskSource, TaskStatus
from harness_shared.tasks import TestsState as TaskTestsState


@pytest.mark.parametrize("secret", ["opaque-repository-key", 'opaque-"key\\with\nnewline'])
def test_planner_prompt_snapshot(secret: str) -> None:
    task = TaskOut(
        id=UUID("00000000-0000-0000-0000-000000000008"),
        kind=TaskKind.PLAN,
        workspace_id="demo",
        parent_id=None,
        text="Добавь экспорт CSV",
        status=TaskStatus.PLANNING,
        priority=0,
        source=TaskSource.TELEGRAM,
        spec_item_id=None,
        branch=None,
        mr_url=None,
        result=None,
        tests_state=TaskTestsState.NOT_RUN,
        created_at=datetime(2026, 10, 26, tzinfo=UTC),
        updated_at=datetime(2026, 10, 26, tzinfo=UTC),
    )
    workspace = Workspace(
        id="demo",
        name="Демо-проект",
        default_branch="develop",
        repo=ProjectRepo(provider="gitlab", project="group/demo"),
    )
    expected = Path(__file__).parent / "fixtures/prompts/planner.md"
    assert build_planner_prompt(task, workspace) == expected.read_text(encoding="utf-8")
    unsafe = task.model_copy(update={"text": f"Экспорт с ключом {secret}"})
    prompt = build_planner_prompt(unsafe, workspace, iter([secret]))
    assert secret not in prompt
    assert "[REDACTED]" in prompt
    assert "access_ref" not in prompt
    unsafe = task.model_copy(update={"text": "ключ glpat-" + "a" * 24})
    assert "glpat-" not in build_planner_prompt(unsafe, workspace)
