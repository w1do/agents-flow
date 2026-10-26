"""Контракт worker-клиента на записанных ответах respx, без ключей и Postgres."""

from pathlib import Path
from uuid import UUID

import httpx
import pytest
import respx
from harness_server.adapters.worker_api import HttpWorkerAPI, WorkerAPIError
from harness_server.worker.client import WorkerClient
from harness_shared.tasks import TaskKind
from harness_shared.worker_reports import CheckpointIn, EventIn, ResultIn, StatusIn

FIXTURES = Path(__file__).parent / "fixtures" / "worker"
BASE = "https://worker.test"
TOKEN = "test-worker-token-0123456789abcdef01"


async def _no_sleep(seconds: float) -> None:
    pass


@pytest.mark.asyncio
@respx.mock
async def test_claim_empty_claim_and_recovery_contracts() -> None:
    route = respx.post(f"{BASE}/worker/tasks/claim")
    fixture = (FIXTURES / "claim.json").read_text()
    route.side_effect = [httpx.Response(200, text=fixture), httpx.Response(200, text="null")]
    async with httpx.AsyncClient() as http:
        client = WorkerClient(HttpWorkerAPI(http, BASE, TOKEN))
        claim = await client.claim(TaskKind.IMPLEMENT, "local")
        assert claim is not None and claim.project.repo.access_ref == "vault:demo/gitlab/main"
        assert await client.claim(TaskKind.IMPLEMENT, "local") is None
        snapshot = {"provider_id": "local", "task_id": str(claim.task.id), "pid": 42}
        respx.post(f"{BASE}/worker/sandbox/recover").respond(
            200,
            json={
                "claim": claim.model_dump(mode="json"),
                "sandbox": snapshot,
            },
        )
        recovery = await client.recover("local")
        assert recovery is not None and recovery.sandbox.pid == 42
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN.encode() not in route.calls[0].request.content


@pytest.mark.parametrize("endpoint", ["events", "status", "checkpoints", "result"])
@pytest.mark.asyncio
@respx.mock
async def test_report_retries_same_key_and_body(endpoint: str) -> None:
    bodies: dict[str, EventIn | CheckpointIn] = {
        "events": EventIn(external_key="one", text="progress"),
        "status": StatusIn.model_validate(
            {"external_key": "one", "text": "progress", "status": "testing"}
        ),
        "checkpoints": CheckpointIn(external_key="one", summary="saved", status="active"),
        "result": ResultIn(external_key="one", text="done"),
    }
    route = respx.post(f"{BASE}/worker/tasks/{UUID(int=1)}/{endpoint}")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, text=(FIXTURES / "event.json").read_text()),
    ]
    async with httpx.AsyncClient() as http:
        client = WorkerClient(HttpWorkerAPI(http, BASE, TOKEN, sleep=_no_sleep))
        event = await client.report(UUID(int=1), endpoint, bodies[endpoint], "test-task-token")
        assert event.id == UUID(int=2)
    assert route.call_count == 2
    assert route.calls[0].request.content == route.calls[1].request.content
    assert route.calls[0].request.headers["X-Task-Token"] == "test-task-token"


@pytest.mark.parametrize("code", [301, 401, 409, 422, 503])
@pytest.mark.asyncio
@respx.mock
async def test_http_errors_are_safe_and_redirects_do_not_forward_tokens(code: int) -> None:
    route = respx.post(f"{BASE}/worker/tasks/claim").respond(
        code, text=TOKEN, headers={"Location": "https://other.test"}
    )
    async with httpx.AsyncClient() as http:
        client = WorkerClient(HttpWorkerAPI(http, BASE, TOKEN, sleep=_no_sleep))
        with pytest.raises(WorkerAPIError) as caught:
            await client.claim(TaskKind.IMPLEMENT, "local")
    assert TOKEN not in str(caught.value) and BASE not in str(caught.value)
    assert caught.value.status_code == code
    assert route.call_count == (3 if code == 503 else 1)


@pytest.mark.asyncio
@respx.mock
async def test_network_error_and_invalid_response_are_safe() -> None:
    route = respx.post(f"{BASE}/worker/tasks/claim").mock(side_effect=httpx.ReadTimeout(TOKEN))
    async with httpx.AsyncClient() as http:
        client = WorkerClient(HttpWorkerAPI(http, BASE, TOKEN, sleep=_no_sleep))
        with pytest.raises(WorkerAPIError, match="network") as caught:
            await client.claim(TaskKind.IMPLEMENT, "local")
        assert TOKEN not in str(caught.value) and route.call_count == 3
        for response in (
            httpx.Response(200, text=TOKEN),
            httpx.Response(200, json={"secret": TOKEN}),
        ):
            route.mock(return_value=response)
            with pytest.raises(WorkerAPIError, match="invalid_response") as invalid:
                await client.claim(TaskKind.IMPLEMENT, "local")
            assert TOKEN not in str(invalid.value)
