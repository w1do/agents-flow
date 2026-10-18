"""Engine и фабрика сессий приложения. Тесты и app.py создают их только через эти функции."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    """Async engine приложения; pool_pre_ping — обрыв соединения после рестарта Postgres.

    Без проверки первый запрос после рестарта БД падает, а готовность продолжает показываться.
    """
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий с expire_on_commit=False.

    Объекты читаются после commit без нового запроса: в async ленивой загрузки нет."""
    return async_sessionmaker(engine, expire_on_commit=False)
