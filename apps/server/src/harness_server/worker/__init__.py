"""Worker машины агента: HTTP-очередь и локальный провайдер, без серверных ENV и БД."""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

import httpx

from harness_server.adapters.local import LocalSandboxProvider
from harness_server.adapters.worker_api import HttpWorkerAPI
from harness_server.config import HarnessConfig
from harness_server.services.machine import require_non_root
from harness_server.worker.client import WorkerClient
from harness_server.worker.dispatcher import build_dispatch_context, dispatch_once
from harness_server.worker.settings import WorkerSettings

logger = logging.getLogger(__name__)


async def run_worker(
    poll_interval_sec: float,
    stop: asyncio.Event,
    dispatch: Callable[[], Awaitable[bool]] | None = None,
) -> None:
    """Остановка отменяет текущий шаг и дожидается его завершения до закрытия HTTP."""
    logger.info("worker started, poll interval %.2f s", poll_interval_sec)
    async with asyncio.TaskGroup() as tasks:
        # SIGTERM должен прерывать и HTTP/backoff внутри dispatch, а не только паузу опроса.
        polling = tasks.create_task(_poll_worker(poll_interval_sec, stop, dispatch))
        await stop.wait()
        polling.cancel()
    logger.info("worker stopped")


async def _poll_worker(
    poll_interval_sec: float,
    stop: asyncio.Event,
    dispatch: Callable[[], Awaitable[bool]] | None,
) -> None:
    while not stop.is_set():
        if dispatch is not None:
            try:
                await dispatch()
            except Exception as exc:
                # Тип, а не текст: в тексте могут быть вывод песочницы или адреса.
                logger.error("dispatch step failed: %s", type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_sec)


async def start_worker(
    settings: WorkerSettings,
    config: HarnessConfig,
    stop: asyncio.Event,
    *,
    http: httpx.AsyncClient | None = None,
) -> None:
    """Ресурсы HTTP закрываются при выходе; серверные операции выполняются только через API."""
    require_non_root()
    client_http = http or httpx.AsyncClient(timeout=15, trust_env=False)
    try:
        client = WorkerClient(
            HttpWorkerAPI(
                client_http,
                settings.harness_public_url,
                settings.worker_api_token.get_secret_value(),
            )
        )
        dispatch = await _build_dispatch(settings, config, client)
        await run_worker(settings.worker_poll_interval_sec, stop, dispatch)
    finally:
        if http is None:
            await client_http.aclose()


async def _build_dispatch(
    settings: WorkerSettings, config: HarnessConfig, client: WorkerClient
) -> Callable[[], Awaitable[bool]] | None:
    """Сборка локального диспетчера не подключается к серверу или БД."""
    provider = LocalSandboxProvider(config.sandbox.provider_id)
    ctx = build_dispatch_context(settings, config, client, provider)
    if ctx is None:
        return None

    async def step() -> bool:
        return await dispatch_once(ctx)

    return step


async def serve_worker(settings: WorkerSettings, config: HarnessConfig) -> None:
    """SIGTERM/SIGINT прерывают текущий шаг и останавливают worker."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await start_worker(settings, config, stop)
