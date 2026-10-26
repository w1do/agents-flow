"""Сервис проектов: каталог на сервере (project-catalog, D-65).

Единственный вход для записи и чтения проектов: API, консоль и бот вызывают эти функции
(CLAUDE.md §3). Каждая функция записи — одна транзакция с commit (D-24). Поля проверяет Pydantic
до вызова; здесь проверяются только конфликт id и статус. access_ref — ссылка на vault, значение
ключа сюда не попадает.
"""

from typing import Any

from harness_shared.projects import (
    ProjectInput,
    ProjectRead,
    ProjectSettings,
    ProjectStatus,
    ProjectUpdate,
    Workspace,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import Project
from harness_server.domain.errors import NotFound, ProjectConflict, ProjectDisabled


async def create_project(session: AsyncSession, data: ProjectInput) -> ProjectRead:
    """Создать проект со статусом active. Занятый id отклоняется, существующий не меняется."""
    if await session.get(Project, data.id) is not None:
        raise ProjectConflict(data.id)
    project = Project(**_columns(data.model_dump()), status=ProjectStatus.ACTIVE)
    session.add(project)
    try:
        await session.commit()
    except IntegrityError as exc:
        # Гонка двух создателей: второй получает тот же ответ, что и при явной проверке выше.
        await session.rollback()
        raise ProjectConflict(data.id) from exc
    await session.refresh(project)
    return ProjectRead.model_validate(project, from_attributes=True)


async def list_projects(session: AsyncSession) -> list[ProjectRead]:
    """Все проекты, включая отключённые: оператор видит каталог целиком."""
    rows = await session.scalars(select(Project).order_by(Project.id))
    return [ProjectRead.model_validate(row, from_attributes=True) for row in rows]


async def get_project(session: AsyncSession, project_id: str) -> ProjectRead:
    """Один проект по id. Отсутствие — NotFound без подробностей."""
    project = await _load(session, project_id)
    return ProjectRead.model_validate(project, from_attributes=True)


async def update_project(
    session: AsyncSession, project_id: str, data: ProjectUpdate
) -> ProjectRead:
    """Изменить переданные поля. Непереданные поля остаются прежними."""
    project = await _load(session, project_id)
    values = data.model_dump(exclude_unset=True)
    if data.repo is not None:
        # Блок repo заменяется целиком: exclude_unset убрал бы из него незаданный access_ref.
        values["repo"] = data.repo.model_dump()
    for column, value in _columns(values).items():
        setattr(project, column, value)
    await session.commit()
    await session.refresh(project)
    return ProjectRead.model_validate(project, from_attributes=True)


async def disable_project(session: AsyncSession, project_id: str) -> ProjectRead:
    """Отключить проект. Задачи в работе не трогаются: их доведёт worker до своего статуса."""
    project = await _load(session, project_id)
    project.status = ProjectStatus.DISABLED
    await session.commit()
    await session.refresh(project)
    return ProjectRead.model_validate(project, from_attributes=True)


async def ensure_accepts_tasks(session: AsyncSession, project_id: str) -> None:
    """Новые задачи по проекту принимаются только для active. Для intake, API и MCP."""
    project = await _load(session, project_id)
    if project.status != ProjectStatus.ACTIVE:
        raise ProjectDisabled(project_id)


async def get_project_settings(session: AsyncSession, project_id: str) -> ProjectSettings:
    """Настройки для локального конфига машины агента. Отключённый проект не выдаётся."""
    project = await _load(session, project_id)
    if project.status != ProjectStatus.ACTIVE:
        raise ProjectDisabled(project_id)
    return ProjectSettings.model_validate(project, from_attributes=True)


async def list_workspaces(session: AsyncSession, *, active_only: bool = True) -> list[Workspace]:
    """Проекты в виде Workspace для бота, маршрутизатора и диагностики; по умолчанию только active.

    Отключённый проект не попадает в кнопки и в список известных id: новые задачи по нему не
    принимаются (project-catalog).
    """
    stmt = select(Project).order_by(Project.id)
    if active_only:
        stmt = stmt.where(Project.status == ProjectStatus.ACTIVE)
    rows = await session.scalars(stmt)
    return [Workspace.model_validate(row, from_attributes=True) for row in rows]


async def get_workspace(session: AsyncSession, project_id: str) -> Workspace:
    """Проект любого статуса по id: задача, принятая до отключения, доводится до конца."""
    project = await _load(session, project_id)
    return Workspace.model_validate(project, from_attributes=True)


async def _load(session: AsyncSession, project_id: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound("project", project_id)
    return project


def _columns(values: dict[str, Any]) -> dict[str, Any]:
    """Переводит блок repo в колонки repo_* таблицы; остальные поля проходят без изменений."""
    result = dict(values)
    repo = result.pop("repo", None)
    if repo is not None:
        result["repo_provider"] = repo["provider"]
        result["repo_base_url"] = repo["base_url"]
        result["repo_project"] = repo["project"]
        result["access_ref"] = repo["access_ref"]
    return result
