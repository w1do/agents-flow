from concurrent.futures import ThreadPoolExecutor

from fastapi import Request

from app.api import rate_limit
from app.api.rate_limit import LoginRateLimiter
from app.api.proxy import client_ip


def test_concurrent_acquire_reserves_only_allowed_attempts():
    limiter = LoginRateLimiter(attempts=5)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: limiter.acquire("person@example.test", "127.0.0.1"), range(20)))
    assert sum(results) == 5


def test_expired_keys_are_cleaned_and_old_key_can_acquire(monkeypatch):
    now = 0.0
    monkeypatch.setattr(rate_limit, "monotonic", lambda: now)
    limiter = LoginRateLimiter(attempts=5, window_seconds=60, ip_attempts=1_000)
    limiter.MAX_KEYS = 1_000
    for index in range(1_000):
        assert limiter.acquire(f"person{index}@example.test", "127.0.0.1")

    now = 61.0
    for index in range(limiter.CLEANUP_EVERY):
        limiter.acquire(f"cleanup{index}@example.test", "127.0.0.1")

    assert len(limiter._failures) <= limiter.MAX_KEYS
    assert limiter.acquire("person0@example.test", "127.0.0.1")


def test_expired_ten_thousand_keys_are_pruned(monkeypatch):
    now = 0.0
    monkeypatch.setattr(rate_limit, "monotonic", lambda: now)
    limiter = LoginRateLimiter(window_seconds=60, ip_attempts=10_000)
    for index in range(limiter.MAX_KEYS):
        ip = f"192.0.{index // 256}.{index % 256}"
        assert limiter.acquire(f"person{index}@example.test", ip)
    now = 61.0
    limiter._prune(now)
    assert len(limiter._failures) <= limiter.MAX_KEYS
    assert len(limiter._ip_failures) <= limiter.MAX_KEYS
    assert not limiter._failures


def test_ip_limit_applies_across_different_emails():
    limiter = LoginRateLimiter(attempts=5, ip_attempts=20)
    results = [limiter.acquire(f"person{index}@example.test", "192.0.2.10")
               for index in range(21)]
    assert sum(results) == 20


def test_retry_after_uses_only_overflowed_buckets(monkeypatch):
    now = 0.0
    monkeypatch.setattr(rate_limit, "monotonic", lambda: now)
    limiter = LoginRateLimiter(attempts=10, window_seconds=60, ip_attempts=5)
    assert limiter.acquire("a@example.test", "192.0.2.10")
    now = 30.0
    for _ in range(4):
        assert limiter.acquire("b@example.test", "192.0.2.10")
    assert not limiter.acquire("b@example.test", "192.0.2.10")
    assert limiter.retry_after("b@example.test", "192.0.2.10") == 30


def test_overflow_evicts_oldest_key():
    limiter = LoginRateLimiter(ip_attempts=100)
    limiter.MAX_KEYS = 2
    for index in range(3):
        limiter.acquire(f"person{index}@example.test", f"192.0.2.{index + 1}")
    assert len(limiter._failures) == 2
    assert len(limiter._ip_failures) == 2


def test_reset_keeps_ip_budget():
    limiter = LoginRateLimiter(attempts=5, ip_attempts=2)
    assert limiter.acquire("success@example.test", "192.0.2.1")
    assert limiter.acquire("other@example.test", "192.0.2.1")
    limiter.reset("success@example.test", "192.0.2.1")
    assert not limiter.acquire("another@example.test", "192.0.2.1")


def test_forwarded_chain_preserves_trusted_ipv4_and_ipv6_networks(monkeypatch):
    request = Request({
        "type": "http", "method": "GET", "path": "/", "headers": [
            (b"x-forwarded-for", b"198.51.100.7, 2001:db8::2"),
        ], "client": ("192.0.2.3", 1234), "scheme": "http", "server": ("test", 80),
        "query_string": b"",
    })
    assert client_ip(request, ["192.0.2.0/24", "2001:db8::/32"]) == "198.51.100.7"


def test_equivalent_ipv6_addresses_share_budget():
    limiter = LoginRateLimiter(attempts=10, ip_attempts=3)
    addresses = ["2001:db8::1", "2001:0db8:0:0:0:0:0:1", "::ffff:2001:db8::1"]
    assert all(limiter.acquire(f"user{index}@example.test", ip)
               for index, ip in enumerate(addresses))
    assert not limiter.acquire("fourth@example.test", addresses[0])
    assert len(limiter._ip_failures) == 1
