"""Worker: цикл диспетчера песочницы (mvp-06) и апдейты Telegram.

При старте дообрабатывает апдейты Telegram и досылает карточки, брошенные до рестарта (D-27).
Ошибка восстановления логируется и не мешает запуску цикла. Если песочница настроена
(local provider),
на каждом шаге цикла запускается диспетчер: без реестра пайплайнов он ничего не делает.
Публичный API пакета (run_worker, start_worker, serve_worker) сохранён после переноса из worker.py.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harness_server.config import HarnessConfig
from harness_server.db.session import create_engine, create_session_factory
from harness_server.services.intake import recover_pending
from harness_server.services.machine import require_non_root
from harness_server.services.projects import list_workspaces
from harness_server.services.sandboxes import ensure_sandbox
from harness_server.settings import Settings
from harness_server.wiring import (
    BotAdapters,
    build_adapters,
    build_bot_context,
    build_http_client,
    build_sandbox_provider,
)
from harness_server.worker.dispatcher import build_dispatch_context, dispatch_once

logger = logging.getLogger(__name__)


async def run_worker(
    poll_interval_sec: float,
    stop: asyncio.Event,
    dispatch: Callable[[], Awaitable[bool]] | None = None,
) -> None:
    """Крутит цикл опроса до установки stop. Ожидание прерывается сразу после установки stop.

    dispatch — один шаг диспетчера песочницы; ошибка шага логируется, цикл продолжается.
    """
    logger.info("worker started, poll interval %.2f s", poll_interval_sec)
    while not stop.is_set():
        if dispatch is not None:
            try:
                await dispatch()
            except Exception as exc:
                # Тип, а не текст: в тексте могут быть вывод песочницы или адреса.
                logger.error("dispatch step failed: %s", type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_sec)
    logger.info("worker stopped")


async def start_worker(
    settings: Settings,
    config: HarnessConfig,
    stop: asyncio.Event,
    *,
    adapters: BotAdapters | None = None,
) -> None:
    """Восстанавливает брошенные апдейты, затем крутит цикл до stop. Ресурсы закрываются при выходе.

    adapters — фейки в тестах; без него строятся реальные адаптеры из настроек.
    """
    require_non_root()
    engine = create_engine(settings.database_url.get_secret_value())
    factory = create_session_factory(engine)
    http = build_http_client()
    try:
        bot = build_bot_context(
            settings,
            factory,
            adapters if adapters is not None else build_adapters(settings, http),
        )
        try:
            await recover_pending(bot)
        except Exception as exc:
            # В тексте исключения может быть строка подключения: в лог уходит только класс.
            logger.warning("telegram recovery failed: %s", type(exc).__name__)
        dispatch = await _build_dispatch(settings, config, factory)
        await run_worker(settings.worker_poll_interval_sec, stop, dispatch)
    finally:
        await http.aclose()
        await engine.dispose()


async def _build_dispatch(
    settings: Settings, config: HarnessConfig, factory: async_sessionmaker[AsyncSession]
) -> Callable[[], Awaitable[bool]] | None:
    """Диспетчер песочницы, если песочница настроена; иначе None и worker работает как прежде."""
    provider = build_sandbox_provider(settings, config.sandbox.provider_id)
    ctx = build_dispatch_context(settings, config, factory, provider)
    if ctx is None:
        return None
    async with factory() as session:
        await ensure_sandbox(session, config)
        workspaces = await list_workspaces(session)
    # Ключи репозиториев — в vault по repo.access_ref; без ключа задачи уходят в error (D-60).
    without_key = [ws.id for ws in workspaces if ws.repo.access_ref is None]
    if without_key:
        logger.warning(
            "проект без repo.access_ref, задачи по нему уходят в error: %s",
            ", ".join(without_key),
        )

    async def step() -> bool:
        return await dispatch_once(ctx)

    return step


async def serve_worker(settings: Settings, config: HarnessConfig) -> None:
    """Запускает worker и переводит SIGTERM/SIGINT в остановку цикла.

    Docker останавливает контейнер сигналом SIGTERM; без обработчика процесс убивался бы на
    полуслове и не дожидался бы завершения текущего шага.
    """
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await start_worker(settings, config, stop)
