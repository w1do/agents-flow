"""Каталог проектов для тестов: проекты заводятся через сервис, как оператор в консоли (D-65).

Тесты рантайма читают проекты из таблицы projects, поэтому нужные проекты заводятся явно.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from harness_server.services.projects import create_project
from harness_shared.projects import ProjectInput, ProjectRepo, Workspace
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DEMO_KEY_REF = "vault:demo/gitlab/main"
DEMO = Workspace(
    id="demo",
    name="Демо-проект",
    voice_aliases=["демо", "демо-проект"],
    repo=ProjectRepo(provider="gitlab", project="group/demo", access_ref=DEMO_KEY_REF),
)
SHOP = Workspace(
    id="shop",
    name="Магазин",
    voice_aliases=["магазин"],
    repo=ProjectRepo(provider="gitlab", project="group/shop"),
)


async def seed_workspaces(
    factory: async_sessionmaker[AsyncSession], *workspaces: Workspace
) -> None:
    """Заводит проекты через сервис проектов с настоящими коммитами."""
    async with factory() as session:
        for workspace in workspaces:
            await create_project(session, ProjectInput.model_validate(workspace.model_dump()))


@contextmanager
def seeded_projects_sync(database_url: str, *workspaces: Workspace) -> Iterator[None]:
    """Для синхронных тестов CLI: свой engine и event loop; по выходу таблица projects очищается."""

    async def seed() -> None:
        engine = create_async_engine(database_url)
        try:
            await seed_workspaces(async_sessionmaker(engine, expire_on_commit=False), *workspaces)
        finally:
            await engine.dispose()

    async def truncate() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("TRUNCATE TABLE projects CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(seed())
    try:
        yield
    finally:
        asyncio.run(truncate())
