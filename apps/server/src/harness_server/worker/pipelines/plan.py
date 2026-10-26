"""Описание plan для диспетчера; выполнение находится в сервисе."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from harness_shared.projects import Workspace
from harness_shared.sandboxes import AgentRole
from harness_shared.tasks import TaskKind, TaskOut, TaskStatus

if TYPE_CHECKING:
    from harness_server.worker.pipeline import AgentRunner, Outcome


@runtime_checkable
class PlanRunner(Protocol):
    async def run_plan(self, task: TaskOut) -> "Outcome": ...


class PlanPipeline:
    kind = TaskKind.PLAN
    from_status = TaskStatus.PLANNING
    to_status: TaskStatus | None = None
    role = AgentRole.PLANNER

    def base_ref(self, task: TaskOut, workspace: Workspace) -> str:
        return f"origin/{workspace.default_branch}"

    async def run(self, runner: "AgentRunner", task: TaskOut) -> "Outcome":
        from harness_server.worker.pipeline import Outcome

        if not isinstance(runner, PlanRunner):
            return Outcome(False, "planner_runtime_required")
        return await runner.run_plan(task)
