from collections import deque
from math import ceil
from time import monotonic


class RateWindow:
    """Shared fixed-duration sliding window operations for limiter buckets."""

    def __init__(self, window_seconds: int):
        self.window_seconds = window_seconds

    def prune(self, entries: deque[float], now: float) -> None:
        while entries and now - entries[0] >= self.window_seconds:
            entries.popleft()

    def acquire(self, entries: deque[float], limit: int, now: float | None = None) -> bool:
        now = monotonic() if now is None else now
        if self.limited(entries, limit, now):
            return False
        entries.append(now)
        return True

    def limited(self, entries: deque[float], limit: int, now: float) -> bool:
        self.prune(entries, now)
        return len(entries) >= limit

    def record(self, entries: deque[float], now: float) -> None:
        entries.append(now)

    def retry_after(self, entries, now: float | None = None) -> int:
        now = monotonic() if now is None else now
        oldest = min(entries) if entries else None
        remaining = self.window_seconds - (now - oldest) if oldest is not None else 1
        return max(1, ceil(remaining))
