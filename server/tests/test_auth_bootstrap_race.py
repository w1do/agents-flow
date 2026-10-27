from sqlalchemy import create_engine, func, select
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.models import Base, User
from app.repositories.user import UserRepository
from app.services.auth import ensure_initial_admin


def test_initial_admin_insert_conflict_keeps_competing_user(session, monkeypatch):
    settings = Settings(database_url="sqlite://", jwt_secret="t" * 32,
                        admin_email="admin@example.test", admin_password="admin-password")
    original_has_users = UserRepository.has_users
    calls = 0

    def insert_competitor_then_report_empty(repository):
        nonlocal calls
        calls += 1
        if calls == 1:
            repository.create(email=settings.admin_email,
                              password_hash=hash_password("competing-password"))
            session.commit()
            return False
        return original_has_users(repository)

    monkeypatch.setattr(UserRepository, "has_users", insert_competitor_then_report_empty)
    ensure_initial_admin(session, settings)

    assert session.scalar(select(func.count()).select_from(User)) == 1
    assert original_has_users(UserRepository(session))


def test_concurrent_bootstrap_creates_exactly_one_admin(engine):
    settings = [
        Settings(database_url="sqlite://", jwt_secret="t" * 32,
                 admin_email=f"admin{index}@example.test", admin_password="admin-password")
        for index in range(2)
    ]

    def bootstrap(config):
        with Session(engine, expire_on_commit=False) as session:
            with session.begin():
                ensure_initial_admin(session, config)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(bootstrap, settings))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1


def test_bootstrap_race_uses_independent_file_connections(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'bootstrap.db'}"
    engines = [create_engine(url, connect_args={"timeout": 10}) for _ in range(2)]
    Base.metadata.create_all(engines[0])
    factories = [sessionmaker(bind=engine, expire_on_commit=False) for engine in engines]
    configs = [Settings(database_url=url, jwt_secret="t" * 32,
                        admin_email=f"admin{index}@example.test",
                        admin_password="admin-password") for index in range(2)]

    def bootstrap(index):
        with factories[index]() as session, session.begin():
            ensure_initial_admin(session, configs[index])

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(bootstrap, range(2)))
        with Session(engines[0]) as session:
            assert session.scalar(select(func.count()).select_from(User)) == 1
    finally:
        for engine in engines:
            engine.dispose()
