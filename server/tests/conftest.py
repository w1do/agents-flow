import asyncio
import os
import socket
from contextlib import suppress
from secrets import token_urlsafe

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.models import Base


@pytest.fixture(autouse=True)
async def sandbox_asyncio_wakeup():
    # Restricted runners can forbid socketpair.send(), breaking thread notifications.
    # Keep the loop awake there so real FastAPI worker threads can finish normally.
    sender, receiver = socket.socketpair()
    with sender, receiver:
        try:
            sender.send(b"\0")
            restricted = False
        except PermissionError:
            restricted = True
    if not restricted:
        yield
        return

    async def tick():
        while True:
            await asyncio.sleep(0.01)

    task = asyncio.create_task(tick())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.fixture
def engine():
    url = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    options = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    database = create_engine(url, hide_parameters=True,
                             **(options if url.startswith("sqlite") else {}))
    if database.dialect.name == "sqlite":
        @event.listens_for(database, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(database)
    yield database
    Base.metadata.drop_all(database)
    database.dispose()


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
        database_session.rollback()


@pytest.fixture
def app(session, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", session.bind.url.render_as_string(hide_password=False))
    monkeypatch.setenv("JWT_SECRET", token_urlsafe(32))
    get_settings.cache_clear()
    from app.core import db
    from app.main import create_app

    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=session.bind))
    application = create_app()
    async def override_db():
        yield session

    application.dependency_overrides[db.get_db] = override_db
    yield application
    application.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
            yield test_client


@pytest.fixture
def admin_user(session):
    import bcrypt

    from app.repositories.user import UserRepository

    return UserRepository(session).create(
        email="admin@example.test",
        password_hash=bcrypt.hashpw(b"correct-password", bcrypt.gensalt(rounds=4)).decode(),
    )


@pytest.fixture
def admin_headers(app, admin_user):
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(str(admin_user.id))}"}


@pytest.fixture
def project(session):
    from app.repositories.project import ProjectRepository

    return ProjectRepository(session).create(name="Demo")
