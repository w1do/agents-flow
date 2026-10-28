from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.security import hash_password, verify_password
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


async def test_lifespan_does_not_create_initial_admin(app, session, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "startup@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "startup-password")
    get_settings.cache_clear()
    for _ in range(2):
        async with app.router.lifespan_context(app):
            pass
    assert session.scalar(select(func.count()).select_from(User)) == 0


