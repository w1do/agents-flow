"""Фикстуры планировщика: агент пишет файлы, worker читает ответы API."""

from pathlib import Path
from uuid import UUID

from harness_server.adapters.sandbox import FakeSandbox
from harness_server.adapters.worker_api import FakeWorkerAPI
from harness_server.services.agent_result import AgentResult, AgentRun, AgentState
from harness_server.services.sandboxes import AgentStart, AgentStartState
from harness_server.worker.client import WorkerClient
from harness_shared.planning import PlanFinishIn, PlanState, SpecItemOut
from harness_shared.sandboxes import AgentRole
from harness_shared.tasks import TaskKind, TaskStatus
from harness_shared.worker import ClaimOut

HOME = "/home/test"
MARKER = "\nHARNESS_TREE_COMPLETE\n"
PATHS = [
    f"openspec/changes/add-export/{path}"
    for path in ("proposal.md", "design.md", "tasks.md", "specs/export/spec.md")
]


def claim_fixture() -> ClaimOut:
    claim = ClaimOut.model_validate_json(
        (Path(__file__).parent / "fixtures/worker/claim.json").read_text()
    )
    return claim.model_copy(
        update={
            "role": AgentRole.PLANNER,
            "task": claim.task.model_copy(
                update={"kind": TaskKind.PLAN, "status": TaskStatus.PLANNING}
            ),
        }
    )


def state_fixture(claim: ClaimOut, count: int = 1) -> PlanState:
    items = [
        SpecItemOut(
            id=UUID(int=100 + i),
            change_id="add-export",
            key=f"add-export#{i + 1}",
            text=f"Часть {i + 1}",
            status="pending",
            plan_task_id=claim.task.id,
        )
        for i in range(count)
    ]
    return PlanState(
        children=[
            claim.task.model_copy(
                update={
                    "id": UUID(int=200 + i),
                    "kind": TaskKind.IMPLEMENT,
                    "status": TaskStatus.BACKLOG,
                    "parent_id": claim.task.id,
                    "spec_item_id": item.id,
                    "text": f"Часть {i + 1}",
                }
            )
            for i, item in enumerate(items)
        ],
        items=items,
        report_status="completed",
    )


class FakePlanner:
    def __init__(self, sandbox: FakeSandbox, claim: ClaimOut, state: PlanState) -> None:
        self.sandbox = sandbox
        self.claim = claim
        self.api = FakeWorkerAPI([state.model_dump(mode="json")])
        self.client = WorkerClient(self.api)
        self.prompts: list[str] = []
        self.finished: list[PlanFinishIn] = []
        self.succeeded = True

    async def run_agent(self, prompt: str) -> AgentStart:
        self.prompts.append(prompt)
        worktree = f"{HOME}/.harness/worktrees/{self.claim.task.id}"
        for path in PATHS:
            await self.sandbox.write_file(self.sandbox.sandbox_id, f"{worktree}/{path}", "spec")
        return AgentStart(AgentStartState.STARTED)

    async def wait_agent(self) -> AgentRun:
        return AgentRun(
            AgentState.FINISHED,
            exit_code=0,
            result=AgentResult("success", not self.succeeded, 2, "session"),
        )

    async def plan_state(self) -> PlanState:
        return await self.client.plan_state(self.claim.task.id, self.claim.task_token)

    async def finish_plan(self, body: PlanFinishIn) -> None:
        self.finished.append(body)


def sandbox_fixture(claim: ClaimOut | None = None) -> FakeSandbox:
    claim = claim or claim_fixture()
    git = f"git -C {HOME}/.harness/worktrees/{claim.task.id}"
    fake = FakeSandbox()
    fake.respond('printf %s "$HOME"', stdout=HOME)
    fake.respond(f"{git} branch", stdout=f"task/{claim.task.id}\n")
    fake.respond(f"{git} ls-tree -r --name-only -z origin/main", stdout=MARKER)
    fake.respond(f"{git} ls-tree -r --name-only -z HEAD", stdout="\0".join(PATHS) + "\0" + MARKER)
    fake.respond(f"{git} diff", stdout="+описание\nHARNESS_DIFF_COMPLETE\n")
    fake.respond(f"{git} rev-parse", stdout="a" * 40)
    return fake
