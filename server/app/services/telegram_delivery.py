"""Bounded per-chat delivery lanes; delayed retries hold no executor slot."""
import asyncio
import logging
from contextlib import suppress
from time import monotonic

from app.integrations.telegram.client import TelegramError

logger = logging.getLogger(__name__)
sleep = asyncio.sleep
timeout = asyncio.timeout
ATTEMPT_TIMEOUT = 30
CHAT_CAPACITY = 16


class ChatQueueFull(asyncio.QueueFull):
    pass


class DeliveryQueue(asyncio.Queue):
    def __init__(self, maxsize):
        super().__init__(maxsize)
        self.pending = {}

    def put_nowait(self, item):
        # Include pending, sleeping and executing notices in the admission bound.
        chat = item[0]
        if self.pending.get(chat, 0) >= CHAT_CAPACITY:
            raise ChatQueueFull
        if self._unfinished_tasks >= self.maxsize:
            raise asyncio.QueueFull
        super().put_nowait(item)
        self.pending[chat] = self.pending.get(chat, 0) + 1

    def task_done(self, chat):
        super().task_done()
        self.pending[chat] -= 1
        if not self.pending[chat]:
            del self.pending[chat]


class Scheduler:
    def __init__(self, runtime):
        self.runtime, self.queue = runtime, DeliveryQueue(maxsize=256)
        self.lanes, self.workers, self.blocked = {}, {}, {}
        self.slots = asyncio.Semaphore(16)

    async def deliver(self, notice):
        chat, text, markup = notice
        self.blocked = {key: due for key, due in self.blocked.items() if due > monotonic()}
        for attempt in range(4):
            while True:
                due = max(self.blocked.get(chat, 0), self.blocked.get(None, 0))
                if due > monotonic():
                    await sleep(due - monotonic())
                    continue
                try:
                    async with self.slots:
                        # A different lane may have learned a bot limit while we waited.
                        if max(self.blocked.get(chat, 0), self.blocked.get(None, 0)) > monotonic():
                            continue
                        async with timeout(ATTEMPT_TIMEOUT):
                            result = await self.runtime.send(chat, text, markup)
                except Exception:
                    result = None
                break
            if isinstance(result, dict):
                return
            delay = result.retry_after if isinstance(result, TelegramError) else None
            delay = delay if delay is not None else min(0.25 * 2**attempt, 8)
            scope = None if isinstance(result, TelegramError) and result.retry_scope == "bot" else chat
            self.blocked[scope] = max(self.blocked.get(scope, 0), monotonic() + delay)
        logger.warning("telegram_notification_delivery_exhausted")

    async def lane(self, chat):
        try:
            while self.lanes[chat]:
                try:
                    await self.deliver(self.lanes[chat].pop(0))
                finally:
                    self.queue.task_done(chat)
        finally:
            self.lanes.pop(chat, None)
            self.workers.pop(chat, None)

    async def run(self):
        while True:
            notice = await self.queue.get()
            chat = notice[0]
            self.lanes.setdefault(chat, []).append(notice)
            if chat not in self.workers:
                self.workers[chat] = asyncio.create_task(self.lane(chat))

    async def close(self):
        workers = list(self.workers.values())
        for worker in workers:
            worker.cancel()
        for worker in workers:
            with suppress(asyncio.CancelledError):
                await worker
