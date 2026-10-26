"""Учёт запуска, heartbeat и очистки через HTTP на записанных ответах."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from harness_server.adapters.worker_api import HttpWorkerAPI
from harness_server.worker.agent_store import RemoteAgentStore
from harness_server.worker.client import WorkerClient
from harness_shared.worker import ClaimOut


@pytest.mark.asyncio
@respx.mock
async def test_remote_store_and_heartbeat_use_server_contract() -> None:
    claim = ClaimOut.model_validate_json(
        (Path(__file__).parent / "fixtures/worker/claim.json").read_text()
    )
    base = f"https://worker.test/worker/tasks/{claim.task.id}"
    state = {"provider_id": "local", "task_id": str(claim.task.id), "started_at": None, "pid": None}
    respx.post(f"{base}/sandbox/state").respond(200, json=state)
    start = respx.post(f"{base}/sandbox/start").respond(200, json={"state": state, "launch": True})
    pid = respx.post(f"{base}/sandbox/pid").respond(200, json={**state, "pid": 42})
    cleanup = respx.post(f"{base}/sandbox/cleanup").respond(
        200, json={**state, "cleanup_started": True}
    )
    release = respx.post(f"{base}/sandbox/release").respond(204)
    heartbeat = respx.post(f"{base}/heartbeat").respond(204)
    async with httpx.AsyncClient() as http:
        client = WorkerClient(HttpWorkerAPI(http, "https://worker.test", "test-worker-token"))
        store = RemoteAgentStore(client, claim, "local")
        assert (await store.info()).started_at is None
        assert await store.record_started(datetime.now(UTC))
        await store.record_pid(42)
        assert (
            await store.issue_token(claim.task.id, None, 60, datetime.now(UTC)) == claim.task_token
        )
        await client.heartbeat(claim.task.id, claim.task_token)
        await store.revoke_tokens(claim.task.id)
        await store.release()
        await store.mark_error()
    assert start.called and pid.called and heartbeat.called and cleanup.called
    assert release.call_count == 2
