"""Полный диспетчер plan: реальный API, фейковая песочница и агент-сервисы."""

from dataclasses import replace

import pytest
from catalog import DEMO, seed_workspaces
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.adapters.vault import FakeVault
from harness_server.adapters.worker_api import HttpWorkerAPI
from harness_server.db.models import Task, TaskToken
from harness_server.services.agent_result import AgentRun
from harness_server.services.agent_tools import invoke
from harness_server.services.sandboxes import AgentStart
from harness_server.vault_ref import VaultRef
from harness_server.worker.client import WorkerClient
from harness_server.worker.context import DispatchContext
from harness_server.worker.dispatcher import dispatch_once
from harness_server.worker.runner import Runner
from harness_shared.planning import AgentReportIn
from harness_shared.tasks import TaskKind
from plan_support import FakePlanner, claim_fixture, sandbox_fixture, state_fixture
from planning_api_support import SECRET_KEY, seed_items
from pydantic import SecretStr
from sqlalchemy import select
from worker_api_support import WORKER, Factory, app_client, queued_task

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize("failure", [None, "invalid", "secret"])
async def test_plan_dispatch_creates_tasks_checks_pushes_and_cleans(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_url: str,
    committed_session_factory: Factory,
    failure: str | None,
) -> None:
    factory = committed_session_factory
    await seed_workspaces(factory, DEMO)
    plan = await queued_task(factory, kind=TaskKind.PLAN)
    fixture = claim_fixture()
    fixture = fixture.model_copy(
        update={
            "task": fixture.task.model_copy(update={"id": plan.id}),
        }
    )
    # Существующие фикстуры команд связываем с реальным plan_id.
    fake = sandbox_fixture(fixture)
    fake.sandbox_id = "local"
    fake.respond(
        f"git -C /home/test/.harness/worktrees/{plan.id} rev-parse --abbrev-ref", exit_code=1
    )
    if failure == "invalid":
        fake.respond("openspec validate add-export", exit_code=1)
    if failure == "secret":
        fake.respond(
            "git -C /home/test/.harness/worktrees/" + str(plan.id) + " diff --no-ext-diff",
            stdout="+opaque-write-key\nHARNESS_DIFF_COMPLETE\n",
        )

    async def started(runner: Runner, prompt: str) -> AgentStart:
        agent = FakePlanner(fake, runner.claim, state_fixture(runner.claim, 3))
        result = await agent.run_agent(prompt)
        await seed_items(factory, runner.claim.task_token, 3)
        async with factory() as session:
            await invoke(
                session,
                runner.claim.task_token,
                SECRET_KEY,
                "report_task",
                AgentReportIn(status="completed", text="три задачи"),
                (),
            )
        return result

    async def waited(runner: Runner) -> AgentRun:
        return await FakePlanner(fake, runner.claim, state_fixture(runner.claim)).wait_agent()

    monkeypatch.setattr(Runner, "run_agent", started)
    monkeypatch.setattr(Runner, "wait_agent", waited)
    telegram = FakeTelegramClient()
    async with app_client(monkeypatch, migrated_database_url) as (app, http):
        app.state.bot = replace(app.state.bot, telegram=telegram)
        ctx = DispatchContext(
            provider=fake,
            config=app.state.config,
            client=WorkerClient(HttpWorkerAPI(http, "http://test", WORKER)),
            oauth_token=SecretStr("test-oauth"),
            agents_flow_url="http://test/mcp",
            timeout_min=60,
            poll_interval_sec=0,
            vault=FakeVault({VaultRef("demo", "gitlab", "main"): "opaque-write-key"}),
        )
        assert await dispatch_once(ctx)
    async with factory() as session:
        stored = await session.get(Task, plan.id)
        assert stored is not None and stored.status == ("ready" if failure is None else "error")
        children = list(await session.scalars(select(Task).where(Task.parent_id == plan.id)))
        assert len(children) == 3
        assert all(
            child.status == ("backlog" if failure is None else "trash") for child in children
        )
        tokens = list(await session.scalars(select(TaskToken).where(TaskToken.task_id == plan.id)))
        assert tokens and all(token.revoked_at is not None for token in tokens)
    assert fake.paused
    pushed = any(" push " in (entry.cmd or "") for entry in fake.journal)
    assert pushed == (failure is None)
    if failure is None:
        assert "спецификация готова, задач: 3" in telegram.sent[0].text
        assert all(f"Часть {i}" in telegram.sent[0].text for i in range(1, 4))
