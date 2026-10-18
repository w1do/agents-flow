"""Worker: цикл диспетчера. Пока очереди нет, цикл только ждёт и проверяет остановку."""

import asyncio
import contextlib
import logging
import signal

logger = logging.getLogger(__name__)


async def run_worker(poll_interval_sec: float, stop: asyncio.Event) -> None:
    """Крутит цикл опроса до установки stop. Ожидание прерывается сразу после установки stop."""
    logger.info("worker started, poll interval %.2f s", poll_interval_sec)
    while not stop.is_set():
        # Здесь появится выбор задачи из очереди (mvp-03 и далее); сейчас задач нет.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_sec)
    logger.info("worker stopped")


async def serve_worker(poll_interval_sec: float) -> None:
    """Запускает worker и переводит SIGTERM/SIGINT в остановку цикла.

    Docker останавливает контейнер сигналом SIGTERM; без обработчика процесс убивался бы на
    полуслове и не дожидался бы завершения текущего шага.
    """
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await run_worker(poll_interval_sec, stop)
