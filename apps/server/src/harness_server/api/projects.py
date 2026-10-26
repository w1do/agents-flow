"""HTTP-вход каталога проектов (project-catalog, D-65): консоль и выдача настроек машине агента.

Тонкий вход: разбирает тело Pydantic-моделью из shared, вызывает services/projects и переводит
ошибки домена в ответы по полю code. Значения полей в ответах не эхоятся: при ошибке проверки
возвращаются только имена полей (CLAUDE.md §3, спецификация project-catalog).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from harness_shared.projects import (
    ProjectInput,
    ProjectRead,
    ProjectSettings,
    ProjectUpdate,
)
from pydantic import ValidationError

from harness_server.api.deps import SessionDep, require_admin_token
from harness_server.domain.errors import DomainError, NotFound, ProjectConflict, ProjectDisabled
from harness_server.services import projects as catalog

# Авторизация — тот же операторский токен, что у /tasks (D-23); отказ — 401 без подробностей.
console_router = APIRouter(
    prefix="/api/console/projects",
    tags=["projects"],
    dependencies=[Depends(require_admin_token)],
)
settings_router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_admin_token)],
)

# Статусы ответа по code доменной ошибки (CLAUDE.md §4: ошибки домена переводят API).
_STATUS_BY_CODE: dict[str, int] = {
    NotFound.code: 404,
    ProjectConflict.code: 409,
    ProjectDisabled.code: 409,
}


def _domain_error(exc: DomainError) -> HTTPException:
    """Ответ по полю code: только код, без текста исключения и введённых значений."""
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 400), detail=exc.code)


def _invalid(fields: list[str]) -> HTTPException:
    """422 с именами полей: значение, которое не прошло проверку, в ответе не показывается."""
    return HTTPException(status_code=422, detail={"code": "invalid_project", "fields": fields})


def _field_names(exc: ValidationError) -> list[str]:
    return sorted(
        {
            ".".join(str(part) for part in error["loc"]) or "body"
            for error in exc.errors(include_input=False, include_url=False, include_context=False)
        }
    )


async def _json_object(request: Request) -> dict[str, Any]:
    """Тело запроса как объект. Не JSON или не объект — 422 без содержимого тела."""
    try:
        data = await request.json()
    except ValueError:
        raise _invalid(["body"]) from None
    if not isinstance(data, dict):
        raise _invalid(["body"])
    return data


@console_router.post("", status_code=201, response_model=ProjectRead)
async def create_project(request: Request, session: SessionDep) -> ProjectRead:
    """Создаёт проект со статусом active. Занятый id — 409, существующий проект не меняется."""
    body = await _json_object(request)
    try:
        data = ProjectInput.model_validate(body)
    except ValidationError as exc:
        raise _invalid(_field_names(exc)) from None
    try:
        return await catalog.create_project(session, data)
    except DomainError as exc:
        raise _domain_error(exc) from None


@console_router.get("", response_model=list[ProjectRead])
async def list_projects(session: SessionDep) -> list[ProjectRead]:
    """Все проекты, включая отключённые."""
    return await catalog.list_projects(session)


@console_router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: str, session: SessionDep) -> ProjectRead:
    """Один проект: ссылка access_ref есть, значения ключа нет."""
    try:
        return await catalog.get_project(session, project_id)
    except DomainError as exc:
        raise _domain_error(exc) from None


@console_router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(project_id: str, request: Request, session: SessionDep) -> ProjectRead:
    """Изменяет переданные поля. Блок repo передаётся целиком."""
    body = await _json_object(request)
    try:
        data = ProjectUpdate.model_validate(body)
    except ValidationError as exc:
        raise _invalid(_field_names(exc)) from None
    try:
        return await catalog.update_project(session, project_id, data)
    except DomainError as exc:
        raise _domain_error(exc) from None


@console_router.post("/{project_id}/disable", response_model=ProjectRead)
async def disable_project(project_id: str, session: SessionDep) -> ProjectRead:
    """Отключает проект: новые задачи и выдача настроек прекращаются, задачи в работе — нет."""
    try:
        return await catalog.disable_project(session, project_id)
    except DomainError as exc:
        raise _domain_error(exc) from None


@settings_router.get("/{project_id}/settings", response_model=ProjectSettings)
async def get_project_settings(project_id: str, session: SessionDep) -> ProjectSettings:
    """Настройки для `agent init`: только поля локального конфига, без значений ключей (D-65)."""
    try:
        return await catalog.get_project_settings(session, project_id)
    except DomainError as exc:
        raise _domain_error(exc) from None
