from datetime import datetime, timedelta, timezone

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.security import decode_token, hash_password, verify_password
from app.models import User
from app.services.auth import ensure_initial_admin


def test_password_hashing():
    hashed = hash_password("correct-password")
    assert hashed != "correct-password"
    assert hashed.startswith("$2")
    assert verify_password("correct-password", hashed)
    assert not verify_password("wrong-password", hashed)
    assert not verify_password("correct-password", "invalid hash")
    assert not verify_password("a" * 73, hashed)


def test_initial_admin_is_created_once(session):
    settings = Settings(database_url="sqlite://", jwt_secret="t" * 32,
                        admin_email="first@example.test", admin_password="first-password")
    ensure_initial_admin(session, settings)
    ensure_initial_admin(session, settings)
    assert session.scalar(select(func.count()).select_from(User)) == 1
    user = session.scalar(select(User))
    assert user.email == settings.admin_email
    assert verify_password("first-password", user.password_hash)
    settings.admin_password = SecretStr("replacement-password")
    ensure_initial_admin(session, settings)
    assert verify_password("first-password", user.password_hash)


def test_initial_admin_preserves_nonempty_table(session, admin_user):
    original_hash = admin_user.password_hash
    settings = Settings(database_url="sqlite://", jwt_secret="t" * 32,
                        admin_email="other@example.test", admin_password="other-password")
    ensure_initial_admin(session, settings)
    assert session.scalar(select(func.count()).select_from(User)) == 1
    assert session.get(User, admin_user.id).password_hash == original_hash


def test_initial_admin_without_credentials(session, monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    settings = Settings(_env_file=None, database_url="sqlite://", jwt_secret="t" * 32)
    ensure_initial_admin(session, settings)
    assert session.scalar(select(func.count()).select_from(User)) == 0


async def test_lifespan_creates_initial_admin(app, session, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "startup@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "startup-password")
    get_settings.cache_clear()
    for _ in range(2):
        async with app.router.lifespan_context(app):
            pass
    assert session.scalar(select(func.count()).select_from(User)) == 1
    user = session.scalar(select(User))
    assert user.email == "startup@example.test"
    assert verify_password("startup-password", user.password_hash)


async def test_login(client, admin_user):
    response = await client.post("/api/v1/auth/login", json={
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
    assert (await client.post("/api/v1/auth/login", json=key)).status_code == 200
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
