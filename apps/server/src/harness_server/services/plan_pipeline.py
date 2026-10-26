"""Выполнение plan через порты агента, песочницы и HTTP-состояния."""

from typing import Protocol

from harness_shared.planning import PlanFinishIn, PlanState
from harness_shared.projects import Workspace
from harness_shared.tasks import TaskOut, TaskStatus
from pydantic import SecretStr

from harness_server.adapters.sandbox import SandboxProvider
from harness_server.services import gates, sandboxes
from harness_server.services.agent_result import AgentRun
from harness_server.services.plan_validation import validate_plan
from harness_server.services.planner_prompt import build_planner_prompt
from harness_server.services.sandboxes import AgentStart


class PlanningAgent(Protocol):
    async def run_agent(self, prompt: str) -> AgentStart: ...
    async def wait_agent(self) -> AgentRun: ...
    async def plan_state(self) -> PlanState: ...
    async def finish_plan(self, body: PlanFinishIn) -> None: ...


async def run_plan(
    agent: PlanningAgent,
    provider: SandboxProvider,
    sandbox_id: str,
    task: TaskOut,
    workspace: Workspace,
    repo_token: SecretStr,
    secrets: tuple[str, ...],
) -> str | None:
    """Публикует только механически проверенный план. Отказ обрабатывает диспетчер."""
    if task.status in {TaskStatus.READY, TaskStatus.ERROR, TaskStatus.STALLED, TaskStatus.TRASH}:
        return None
    await agent.run_agent(build_planner_prompt(task, workspace, secrets))
    run = await agent.wait_agent()
    if not run.succeeded:
        return run.reason or "planner_failed"
    state = await agent.plan_state()
    if state.report_status != "completed":
        return "planner_not_completed"
    worktree = sandboxes.worktree_dir(await sandboxes.home_dir(provider, sandbox_id), task.id)
    base_ref = f"origin/{workspace.default_branch}"
    branch = f"task/{task.id}"
    reason = await validate_plan(provider, sandbox_id, worktree, base_ref, branch, state)
    if reason is not None:
        return reason
    scanned = await gates.secret_scan(provider, sandbox_id, worktree, base_ref, secrets)
    if not scanned.ok:
        return scanned.reason or "secret_scan"
    published = await gates.push(provider, sandbox_id, worktree, branch, workspace.repo, repo_token)
    if not published.ok:
        return published.reason or "push"
    await agent.finish_plan(
        PlanFinishIn(
            external_key="plan-ready",
            status="ready",
            branch=branch,
            text=f"спецификация готова, задач: {len(state.children)}",
        )
    )
    return None
