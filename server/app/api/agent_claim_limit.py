from collections import deque
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import HTTPException


class AgentClaimLimiter:
    def __init__(self, attempts=20, window_seconds=60):
        self.attempts, self.window_seconds = attempts, window_seconds
        self._attempts: dict[str, deque[float]] = {}
        self._lock = Lock()

    def acquire(self, agent_id):
        with self._lock:
            now = monotonic()
            entries = self._attempts.setdefault(str(agent_id), deque())
            while entries and now - entries[0] >= self.window_seconds:
                entries.popleft()
            if len(entries) >= self.attempts:
                return False
            entries.append(now)
            return True

    def retry_after(self, agent_id):
        with self._lock:
            entries = self._attempts.get(str(agent_id), ())
            remaining = self.window_seconds - (monotonic() - entries[0]) if entries else 1
            return max(1, ceil(remaining))


claim_limiter = AgentClaimLimiter()


def check_claim_limit(agent_id):
    if not claim_limiter.acquire(agent_id):
        retry_after = claim_limiter.retry_after(agent_id)
        raise HTTPException(429, "Too Many Requests", headers={"Retry-After": str(retry_after)})
