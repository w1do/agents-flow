"""Настоящие git и openspec validate, локальный bare origin и фейковый агент."""

import shlex
from collections.abc import Callable
from pathlib import Path

import pytest
from harness_server.adapters.local import LocalSandboxProvider
from harness_server.services import git_access
from harness_server.services.agent_result import AgentResult, AgentRun, AgentState
from harness_server.services.plan_pipeline import run_plan
from harness_server.services.sandboxes import AgentStart, AgentStartState
from harness_shared.planning import PlanFinishIn, PlanState
from harness_shared.projects import ProjectRepo
from plan_support import claim_fixture, state_fixture
from pydantic import SecretStr

TOKEN = "opaque-issued-test-key"


async def test_real_git_and_openspec_publish_valid_plan(
    tmp_path: Path,
    owned_local_origin_git_access: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = claim_fixture()
    provider = LocalSandboxProvider("local")
    worktree = tmp_path / ".harness/worktrees" / str(claim.task.id)
    worktree.mkdir(parents=True)
    origin = tmp_path / "origin.git"

    async def command(args: list[str]) -> str:
        result = await provider.exec(
            "local",
            shlex.join(args),
            envs=git_access.anonymous_git_env(),
            timeout_s=5,
        )
        assert result.exit_code == 0, result.stderr
        return result.stdout

    await command(["git", "init", "--bare", str(origin)])
    await command(["git", "init", "-b", "main", str(worktree)])
    git = ["git", "-C", str(worktree)]
    author = ["-c", "user.name=Test", "-c", "user.email=test@example.test"]
    (worktree / "README.md").write_text("base\n")
    await command([*git, "add", "README.md"])
    await command([*git, *author, "commit", "-m", "base"])
    await command([*git, "update-ref", "refs/remotes/origin/main", "HEAD"])
    await command([*git, "switch", "-c", f"task/{claim.task.id}"])
    owned_local_origin_git_access(str(origin))
    auth_env = git_access.git_auth_env

    def local_auth(repo: ProjectRepo, token: str) -> dict[str, str]:
        # Только принадлежащий тесту bare origin, как в owned_local_origin_git_access.
        return {**auth_env(repo, token), "GIT_ALLOW_PROTOCOL": "file:https"}

    monkeypatch.setattr(git_access, "git_auth_env", local_auth)

    async def home(_provider: object, _sandbox: str) -> str:
        return str(tmp_path)

    monkeypatch.setattr("harness_server.services.sandboxes.home_dir", home)

    class Agent:
        def __init__(self) -> None:
            self.finished: list[PlanFinishIn] = []

        async def run_agent(self, prompt: str) -> AgentStart:
            assert TOKEN not in prompt
            directory = worktree / "openspec/changes/add-export"
            for name, text in {
                "proposal.md": "# Export\n\n## Why\nExport CSV.\n",
                "design.md": "# Design\nCSV streaming.\n",
                "tasks.md": "## 1. Export\n- [ ] Add CSV\n",
                "specs/export/spec.md": (
                    "## ADDED Requirements\n\n### Requirement: CSV\n"
                    "The system SHALL export CSV.\n\n#### Scenario: Download\n"
                    "- **WHEN** export is requested\n- **THEN** CSV is returned\n"
                ),
            }.items():
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            await command([*git, "add", "openspec"])
            await command([*git, *author, "commit", "-m", "specification"])
            return AgentStart(AgentStartState.STARTED)

        async def wait_agent(self) -> AgentRun:
            return AgentRun(AgentState.FINISHED, 0, AgentResult("success", False, 2, "s"))

        async def plan_state(self) -> PlanState:
            return state_fixture(claim)

        async def finish_plan(self, body: PlanFinishIn) -> None:
            self.finished.append(body)

    agent = Agent()
    assert (
        await run_plan(
            agent,
            provider,
            "local",
            claim.task,
            claim.project,
            SecretStr(TOKEN),
            (TOKEN,),
        )
        is None
    )
    assert agent.finished[0].status == "ready"
    remote = await command(["git", "--git-dir", str(origin), "rev-parse", f"task/{claim.task.id}"])
    assert remote == await command([*git, "rev-parse", "HEAD"])
