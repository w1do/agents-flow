from collections import deque
import hashlib
import ipaddress
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request

from app.api.rate_window import RateWindow
from app.schemas.auth import LoginRequest


class LoginRateLimiter:
    MAX_KEYS = 10_000
    CLEANUP_EVERY = 64

    def __init__(self, attempts: int = 5, window_seconds: int = 60,
                 ip_attempts: int = 20):
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._ip_failures: dict[str, deque[float]] = {}
        self.ip_attempts = ip_attempts
        self._lock = Lock()
        self._calls = 0
        self._window = RateWindow(window_seconds)

    def _prune(self, now: float) -> None:
        for key, attempts in list(self._failures.items()):
            self._window.prune(attempts, now)
            if not attempts:
                self._failures.pop(key, None)
        while len(self._failures) > self.MAX_KEYS:
            oldest = min(self._failures, key=lambda key: self._failures[key][-1])
            self._failures.pop(oldest, None)
        for ip, attempts in list(self._ip_failures.items()):
            self._window.prune(attempts, now)
            if not attempts:
                self._ip_failures.pop(ip, None)
        while len(self._ip_failures) > self.MAX_KEYS:
            oldest = min(self._ip_failures, key=lambda ip: self._ip_failures[ip][-1])
            self._ip_failures.pop(oldest, None)

    @staticmethod
    def _canonical_ip(ip: str) -> str:
        try:
            address = ipaddress.ip_address(ip)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                return str(address.ipv4_mapped)
            return address.compressed
        except ValueError:
            if ip.startswith("::ffff:"):
                try:
                    return ipaddress.IPv6Address(ip[7:]).compressed
                except ValueError:
                    pass
            return ip

    @classmethod
    def _ip_key(cls, ip: str) -> str:
        return hashlib.sha256(cls._canonical_ip(ip).encode()).hexdigest()

    @classmethod
    def _key(cls, email: str, ip: str) -> str:
        value = f"{email.casefold()}\0{cls._canonical_ip(ip)}"
        return hashlib.sha256(value.encode()).hexdigest()

    def acquire(self, email: str, ip: str) -> bool:
        key, ip_key = self._key(email, ip), self._ip_key(ip)
        with self._lock:
            now = monotonic()
            self._calls += 1
            if self._calls % self.CLEANUP_EVERY == 0:
                self._prune(now)
            ip_failures = self._ip_failures.setdefault(ip_key, deque())
            if self._window.limited(ip_failures, self.ip_attempts, now):
                return False
            failures = self._failures.setdefault(key, deque())
            self._window.prune(failures, now)
            if not failures:
                self._failures.pop(key, None)
                failures = self._failures.setdefault(key, deque())
            if self._window.limited(failures, self.attempts, now):
                return False
            self._window.record(failures, now)
            self._window.record(ip_failures, now)
            if len(self._failures) > self.MAX_KEYS:
                oldest = min(self._failures, key=lambda item: self._failures[item][-1])
                self._failures.pop(oldest, None)
            if len(self._ip_failures) > self.MAX_KEYS:
                oldest_ip = min(self._ip_failures, key=lambda item: self._ip_failures[item][-1])
                self._ip_failures.pop(oldest_ip, None)
            return True

    def retry_after(self, email: str, ip: str) -> int:
        with self._lock:
            attempts = self._failures.get(self._key(email, ip), ())
            ip_attempts = self._ip_failures.get(self._ip_key(ip), ())
            buckets = []
            if len(attempts) >= self.attempts:
                buckets.append(attempts)
            if len(ip_attempts) >= self.ip_attempts:
                buckets.append(ip_attempts)
            oldest = [bucket[0] for bucket in buckets if bucket]
            return self._window.retry_after(oldest, monotonic())

    def reset(self, email: str, ip: str) -> None:
        with self._lock:
            self._failures.pop(self._key(email, ip), None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()
            self._ip_failures.clear()


login_limiter = LoginRateLimiter()


class LoginLimit:
    def __init__(self, email: str, ip: str):
        self.email = email
        self.ip = ip

    def reset_after_success(self) -> None:
        login_limiter.reset(self.email, self.ip)


def login_rate_limit(request: Request, body: LoginRequest) -> LoginLimit:
    ip = request.client.host if request.client else "unknown"
    if not login_limiter.acquire(body.email, ip):
        retry_after = login_limiter.retry_after(body.email, ip)
        raise HTTPException(429, "Too Many Requests", headers={"Retry-After": str(retry_after)})
    return LoginLimit(body.email, ip)
