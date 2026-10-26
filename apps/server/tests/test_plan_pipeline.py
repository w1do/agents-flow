"""План выполняет проверки до push и не доверяет одному completed."""

import pytest
from harness_server.services.plan_pipeline import run_plan
from harness_server.worker.pipeline import PIPELINES
from harness_shared.tasks import TaskKind, TaskStatus
from plan_support import (
    HOME,
    MARKER,
    PATHS,
    FakePlanner,
    claim_fixture,
    sandbox_fixture,
    state_fixture,
)
from pydantic import SecretStr

TOKEN = SecretStr("opaque-repo-write-key")


async def test_plan_is_registered_and_successful() -> None:
    claim = claim_fixture()
    sandbox = sandbox_fixture()
    agent = FakePlanner(sandbox, claim, state_fixture(claim))
    pipeline = PIPELINES[TaskKind.PLAN]
    assert pipeline.base_ref(claim.task, claim.project) == "origin/main"
    assert (
        await run_plan(
            agent,
            sandbox,
            sandbox.sandbox_id,
            claim.task,
            claim.project,
            TOKEN,
            (TOKEN.get_secret_value(), claim.task_token),
        )
        is None
    )
    assert agent.finished[0].status == "ready"
    assert agent.finished[0].branch == f"task/{claim.task.id}"
    assert TOKEN.get_secret_value() not in agent.prompts[0]
    for path in PATHS:
        assert (
            await sandbox.read_file(
                sandbox.sandbox_id,
                f"{HOME}/.harness/worktrees/{claim.task.id}/{path}",
            )
            == "spec"
        )
    commands = [entry.cmd or "" for entry in sandbox.journal]
    validate = commands.index("openspec validate add-export")
    pushed = next(i for i, cmd in enumerate(commands) if " push " in cmd)
    assert validate < pushed
    assert agent.api.calls[0][0].endswith("/plan/state")


@pytest.mark.parametrize("status", [TaskStatus.READY, TaskStatus.ERROR])
async def test_recovery_of_terminal_plan_does_not_restart_agent(status: TaskStatus) -> None:
    claim = claim_fixture()
    sandbox = sandbox_fixture()
    agent = FakePlanner(sandbox, claim, state_fixture(claim))
    task = claim.task.model_copy(update={"status": status})
    assert (
        await run_plan(
            agent,
            sandbox,
            sandbox.sandbox_id,
            task,
            claim.project,
            TOKEN,
            (),
        )
        is None
    )
    assert not agent.prompts and not agent.finished and not sandbox.journal


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("invalid", "plan_invalid_spec"),
        ("secret", "secret_scan_found"),
        ("no_children", "plan_no_implementations"),
        ("uncommitted", "plan_uncommitted"),
        ("old_change", "plan_new_change"),
        ("incomplete", "plan_artifacts"),
        ("no_report", "planner_not_completed"),
        ("failed", "planner_failed"),
        ("truncated", "plan_tree"),
        ("push", "push_failed"),
    ],
)
async def test_rejected_plan_never_becomes_ready(failure: str, reason: str) -> None:
    claim = claim_fixture()
    fake = sandbox_fixture()
    state = state_fixture(claim, 0 if failure == "no_children" else 1)
    if failure == "no_report":
        state.report_status = None
    agent = FakePlanner(fake, claim, state)
    git = f"git -C {HOME}/.harness/worktrees/{claim.task.id}"
    if failure == "invalid":
        fake.respond("openspec validate add-export", exit_code=1, stderr=TOKEN.get_secret_value())
    elif failure == "secret":
        fake.respond(
            f"{git} diff --no-ext-diff",
            stdout=f"+{TOKEN.get_secret_value()}\nHARNESS_DIFF_COMPLETE\n",
        )
    elif failure == "uncommitted":
        fake.respond(f"{git} status", stdout="?? openspec/changes/another/")
    elif failure == "old_change":
        fake.respond(
            f"{git} ls-tree -r --name-only -z origin/main --", stdout=PATHS[0] + "\0" + MARKER
        )
    elif failure in ("truncated", "incomplete"):
        output = "truncated" if failure == "truncated" else PATHS[0] + "\0" + MARKER
        fake.respond(f"{git} ls-tree -r --name-only -z HEAD --", stdout=output)
    elif failure == "failed":
        agent.succeeded = False
    elif failure == "push":
        fake.respond(f"{git} push", exit_code=1, stderr=TOKEN.get_secret_value())
    actual = await run_plan(
        agent,
        fake,
        fake.sandbox_id,
        claim.task,
        claim.project,
        TOKEN,
        (TOKEN.get_secret_value(),),
    )
    assert actual == reason
    assert TOKEN.get_secret_value() not in actual
    assert not agent.finished
    if failure != "push":
        assert not any(" push " in (entry.cmd or "") for entry in fake.journal)
