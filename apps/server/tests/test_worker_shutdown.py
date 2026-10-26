"""Остановка worker прерывает HTTP-ожидание, даже когда сервер не отвечает."""

import asyncio

import httpx
import pytest
from conftest import EXAMPLE_CONFIG
from harness_server.config import load_config
from harness_server.worker import run_worker, start_worker
from harness_server.worker.settings import WorkerSettings


@pytest.mark.parametrize("path", ["/worker/sandbox/recover", "/worker/tasks/claim"])
async def test_stop_cancels_pending_worker_request(path: str) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    stop = asyncio.Event()
    calls: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == path:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return httpx.Response(204)

    settings = WorkerSettings.model_validate(
        {
            "harness_config": EXAMPLE_CONFIG,
            "harness_public_url": "http://127.0.0.1:8000",
            "worker_api_token": "test-worker-token-0123456789abcdef01",
            "claude_code_oauth_token": "test-oauth-token",
            "worker_poll_interval_sec": 60,
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), timeout=None) as http:
        worker = asyncio.create_task(
            start_worker(settings, load_config(EXAMPLE_CONFIG), stop, http=http)
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            stop.set()
            await asyncio.wait_for(worker, timeout=1)
            assert cancelled.is_set()
            assert calls == (
                [path] if path.endswith("recover") else ["/worker/sandbox/recover", path]
            )
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


async def test_stop_interrupts_poll_interval() -> None:
    stop = asyncio.Event()
    dispatched = asyncio.Event()

    async def dispatch() -> bool:
        dispatched.set()
        return False

    worker = asyncio.create_task(run_worker(60, stop, dispatch))
    try:
        await asyncio.wait_for(dispatched.wait(), timeout=1)
        stop.set()
        await asyncio.wait_for(worker, timeout=1)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
