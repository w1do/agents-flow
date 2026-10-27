from collections import deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from app.api.rate_window import RateWindow


class AgentClaimLimiter:
    def __init__(self, attempts=20, window_seconds=60):
        self.attempts, self.window_seconds = attempts, window_seconds
        self._attempts: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._window = RateWindow(window_seconds)

    def acquire(self, agent_id):
        with self._lock:
            entries = self._attempts.setdefault(str(agent_id), deque())
            return self._window.acquire(entries, self.attempts, monotonic())

    def retry_after(self, agent_id):
        with self._lock:
            entries = self._attempts.get(str(agent_id), ())
            return self._window.retry_after(entries, monotonic())


claim_limiter = AgentClaimLimiter()


def check_claim_limit(agent_id):
    if not claim_limiter.acquire(agent_id):
        retry_after = claim_limiter.retry_after(agent_id)
        raise HTTPException(429, "Too Many Requests", headers={"Retry-After": str(retry_after)})
