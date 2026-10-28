from httpx import ASGITransport, AsyncClient
from fastapi import Request
import pytest

from app.api.proxy import client_ip, request_is_secure
from app.api.rate_limit import LoginRateLimiter, login_limiter
from app.core.config import get_settings


def _request(peer):
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [
        (b"x-forwarded-proto", b"https")], "client": (peer, 8001),
        "scheme": "http", "server": ("test", 80), "query_string": b""})


async def test_ipv6_wildcard_proxy_sets_secure_cookie(app, admin_user, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_IPS", '["::/0"]')
    get_settings.cache_clear()
    client = AsyncClient(transport=ASGITransport(app=app, client=("2001:db8::2", 8001)),
                         base_url="http://test")
    async with client:
        response = await client.post("/api/v1/auth/login", json={
            "email": admin_user.email, "password": "correct-password"},
            headers={"X-Forwarded-Proto": "https"})
    assert "secure" in response.headers["set-cookie"].lower()
    get_settings.cache_clear()


@pytest.mark.parametrize(("trusted", "peer", "expected"), [
    ("2001:db8::/32", "2001:db8::5", True),
    ("2001:db8::/32", "2001:db9::5", False),
    ("::/0", "::ffff:192.0.2.3", True),
    ("::/80", "::ffff:192.0.2.3", True),
    ("::/0", "192.0.2.3", False),
    (["2001:db8::/32", "192.0.2.0/24"], "2001:db8::5", True),
    (["2001:db8::/32", "192.0.2.0/24"], "::ffff:192.0.2.5", True),
])
def test_ipv6_and_mixed_proxy_allowlists(trusted, peer, expected):
    networks = trusted if isinstance(trusted, list) else [trusted]
    assert request_is_secure(_request(peer), networks) is expected


@pytest.mark.parametrize(("trusted", "peer"), [
    ("::ffff:192.0.2.3/128", "192.0.2.3"),
    ("192.0.2.3/32", "::ffff:192.0.2.3"),
    ("::ffff:1.2.3.0/120", "1.2.3.5"),
    ("1.2.3.0/24", "::ffff:1.2.3.5"),
])
async def test_mapped_proxy_trust_keeps_secure_cookie_and_client_buckets(
        app, admin_user, monkeypatch, trusted, peer):
    monkeypatch.setenv("TRUSTED_PROXY_IPS", f'["{trusted}"]')
    get_settings.cache_clear()
    login_limiter.clear()
    body = {"email": admin_user.email, "password": "correct-password"}
    client = AsyncClient(transport=ASGITransport(app=app, client=(peer, 8001)),
                         base_url="http://test")
    async with client:
        response = await client.post("/api/v1/auth/login", json=body,
                                     headers={"X-Forwarded-Proto": "https"})
    assert "secure" in response.headers["set-cookie"].lower()

    addresses = []
    for forwarded in ("198.51.100.10", "198.51.100.11"):
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": [
            (b"x-forwarded-for", forwarded.encode())], "client": (peer, 8001),
            "scheme": "http", "server": ("test", 80), "query_string": b""})
        addresses.append(client_ip(request, [trusted]))
    limiter = LoginRateLimiter()
    assert addresses == ["198.51.100.10", "198.51.100.11"]
    assert all(limiter.acquire(f"user{index}@example.test", ip)
               for index, ip in enumerate(addresses))
    assert len(limiter._ip_failures) == 2

    login_limiter.clear()
    untrusted = AsyncClient(transport=ASGITransport(app=app, client=("198.51.100.9", 8002)),
                            base_url="http://test")
    async with untrusted:
        response = await untrusted.post("/api/v1/auth/login", json=body,
                                        headers={"X-Forwarded-Proto": "https"})
    assert "secure" not in response.headers["set-cookie"].lower()
    get_settings.cache_clear()


def test_wide_ipv6_allowlist_keeps_mapped_peer_clients_in_distinct_buckets():
    limiter = LoginRateLimiter()
    addresses = []
    for forwarded in ("198.51.100.10", "198.51.100.11"):
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": [
            (b"x-forwarded-for", forwarded.encode())], "client": ("::ffff:192.0.2.3", 8001),
            "scheme": "http", "server": ("test", 80), "query_string": b""})
        addresses.append(client_ip(request, ["::/0"]))
    assert addresses == ["198.51.100.10", "198.51.100.11"]
    assert all(limiter.acquire(f"user{index}@example.test", ip)
               for index, ip in enumerate(addresses))
    assert len(limiter._ip_failures) == 2
