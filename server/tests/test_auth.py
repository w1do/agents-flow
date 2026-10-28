from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import decode_token


async def test_login(client, admin_user):
    response = await client.post("/api/v1/auth/login", json={
        "email": admin_user.email, "password": "correct-password",
    })
    assert response.status_code == 204
    assert response.content == b""
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert (await client.get("/api/v1/projects")).status_code == 200


async def test_token_endpoint_returns_bearer_token(client, admin_user):
    response = await client.post("/api/v1/auth/token", json={
        "email": admin_user.email, "password": "correct-password",
    })
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["expires_in"] == 12 * 60 * 60
    token = response.json()["access_token"]
    claims = decode_token(token)
    assert claims["sub"] == str(admin_user.id)
    assert claims["exp"] - claims["iat"] == 12 * 60 * 60
    assert (await client.get("/api/v1/projects", headers={
        "Authorization": f"Bearer {token}",
    })).status_code == 200


async def test_cookie_auth_requires_csrf_header_for_mutations(client, admin_user):
    login_response = await client.post("/api/v1/auth/login", json={
        "email": admin_user.email, "password": "correct-password",
    })
    assert login_response.status_code == 204
    assert (await client.get("/api/v1/auth/session")).status_code == 204
    assert (await client.post("/api/v1/projects", json={"name": "No header"})).status_code == 403
    created = await client.post("/api/v1/projects", json={"name": "Cookie project"}, headers={
        "X-Requested-With": "XMLHttpRequest", "Idempotency-Key": "cookie-project-1",
    })
    assert created.status_code == 201
    token_response = await client.post("/api/v1/auth/token", json={
        "email": admin_user.email, "password": "correct-password",
    })
    token = token_response.json()["access_token"]
    bearer_created = await client.post("/api/v1/projects", json={"name": "CLI project"}, headers={
        "Authorization": f"Bearer {token}", "Idempotency-Key": "cli-project-1",
    })
    assert bearer_created.status_code == 201


async def test_logout_clears_cookie(client, admin_user):
    await client.post("/api/v1/auth/login", json={"email": admin_user.email, "password": "correct-password"})
    response = await client.post("/api/v1/auth/logout", headers={"X-Requested-With": "XMLHttpRequest"})
    assert response.status_code == 204
    assert 'session=""' in response.headers["set-cookie"]


@pytest.mark.parametrize("email,password", [
    ("admin@example.test", "wrong-password"), ("unknown@example.test", "correct-password"),
])
async def test_login_rejects_bad_credentials(client, admin_user, email, password):
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_login_rate_limit_and_success_reset(client, admin_user):
    from app.api.rate_limit import login_limiter

    login_limiter.clear()
    body = {"email": "throttle@example.test", "password": "wrong"}
    for _ in range(5):
        assert (await client.post("/api/v1/auth/login", json=body)).status_code == 401
    limited = await client.post("/api/v1/auth/login", json=body)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0
    key = {"email": admin_user.email, "password": "correct-password"}
    for _ in range(4):
        assert (await client.post("/api/v1/auth/login", json=key | {"password": "wrong"})).status_code == 401
    assert (await client.post("/api/v1/auth/login", json=key)).status_code == 204
    assert (await client.post("/api/v1/auth/login", json=key | {"password": "wrong"})).status_code == 401
    login_limiter.clear()


async def test_login_rejects_unknown_fields(client):
    response = await client.post("/api/v1/auth/login", json={
        "email": "admin@example.test", "password": "x", "extra": True,
    })
    assert response.status_code == 422


async def test_login_rejects_invalid_email(client):
    response = await client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "x"})
    assert response.status_code == 422


async def test_login_rejects_oversized_email_without_rate_limit_key(client):
    from app.api.rate_limit import login_limiter
    login_limiter.clear()
    response = await client.post("/api/v1/auth/login", json={"email": "a" * 5000, "password": "x"})
    assert response.status_code == 422
    assert not login_limiter._failures


@pytest.mark.parametrize("authorization", [None, "Bearer broken-token", "Basic invalid", "Bearer"])
async def test_admin_requires_valid_token(client, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = await client.get("/api/v1/projects", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"


async def test_expired_token(client, admin_user):
    now = datetime.now(timezone.utc)
    token = jwt.encode({"sub": str(admin_user.id), "iat": now - timedelta(hours=13),
                        "exp": now - timedelta(hours=1)},
                       get_settings().jwt_secret.get_secret_value(), algorithm="HS256")
    response = await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
