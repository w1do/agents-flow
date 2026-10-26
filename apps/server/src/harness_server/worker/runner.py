"""Локальный запуск и наблюдение агента; серверные сведения доступны через HTTP."""

import asyncio
import logging
from typing import TYPE_CHECKING

from harness_shared.planning import PlanFinishIn, PlanState
from harness_shared.tasks import TaskOut
from harness_shared.worker import ClaimOut
from harness_shared.worker_reports import ResultIn
from pydantic import SecretStr

from harness_server.adapters.worker_api import WorkerAPIError
from harness_server.services import sandboxes
from harness_server.services.agent_result import AgentRun, AgentState, truncate_log_text
from harness_server.services.sandboxes import AgentStart
from harness_server.worker.agent_store import RemoteAgentStore
from harness_server.worker.context import DispatchContext

if TYPE_CHECKING:
    from harness_server.worker.pipeline import Outcome


class Runner:
    """Runner одного закрепления; redaction накапливает секреты текущего процесса."""

    def __init__(self, ctx: DispatchContext, claim: ClaimOut, provider_id: str) -> None:
        self.ctx = ctx
        self.claim = claim
        self.provider_id = provider_id
        self.store = RemoteAgentStore(ctx.client, claim, provider_id)
        self.secrets = (*ctx.secrets, claim.task_token)
        self.repo_token: SecretStr | None = None

    async def plan_state(self) -> PlanState:
        return await self.ctx.client.plan_state(self.claim.task.id, self.claim.task_token)

    async def finish_plan(self, body: PlanFinishIn) -> None:
        await self.ctx.client.plan_finish(self.claim.task.id, body, self.claim.task_token)

    async def run_plan(self, task: TaskOut) -> "Outcome":
        from harness_server.services.plan_pipeline import run_plan
        from harness_server.worker.pipeline import Outcome

        if self.repo_token is None:
            return Outcome(False, "repo_access_ref")
        reason = await run_plan(
            self,
            self.ctx.provider,
            self.provider_id,
            task,
            self.claim.project,
            self.repo_token,
            self.secrets,
        )
        return Outcome(reason is None, reason)

    async def run_agent(self, prompt: str) -> AgentStart:
        return await sandboxes.run_agent(
            self.store,
            self.ctx.provider,
            self.provider_id,
            self.claim.task,
            prompt=prompt,
            max_turns=self.claim.project.agent_max_turns,
            timeout_min=self.ctx.timeout_min,
            oauth_token=self.ctx.oauth_token,
            agents_flow_url=self.ctx.agents_flow_url,
            now=self.ctx.clock(),
            extra_envs=sandboxes.git_author_env(self.ctx.config.sandbox.git_author),
            memory_enabled=self.ctx.config.sandbox.memory is not None,
        )

    async def wait_agent(self) -> AgentRun:
        while True:
            info = await self.store.info()
            run = await sandboxes.wait_agent(
                self.ctx.provider,
                self.provider_id,
                self.claim.task,
                started_at=info.started_at,
                pid=info.pid,
                timeout_min=self.ctx.timeout_min,
                now=self.ctx.clock(),
                secrets=self.secrets,
            )
            if run.state is not AgentState.RUNNING:
                break
            await self.ctx.sleep(self.ctx.poll_interval_sec)
        if run.succeeded and run.result is not None:
            text = f"агент завершён: ходов {run.result.num_turns}, итог {run.result.subtype}"
        else:
            text = f"агент: {run.reason or run.state}, код {run.exit_code}"
            if run.stderr_tail:
                text = f"{text}\n{run.stderr_tail}"
        await self.ctx.client.report(
            self.claim.task.id,
            "result",
            ResultIn(
                external_key=f"agent-result:{info.started_at}",
                text=truncate_log_text(text),
            ),
            self.claim.task_token,
        )
        return run


async def heartbeat(ctx: DispatchContext, claim: ClaimOut) -> None:
    while True:
        try:
            await ctx.client.heartbeat(claim.task.id, claim.task_token)
        except WorkerAPIError as exc:
            logging.getLogger(__name__).warning("worker heartbeat failed reason=%s", exc.reason)
        await asyncio.sleep(10)
