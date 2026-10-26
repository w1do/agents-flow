"""Сервис проектов на реальном Postgres: конфликт id, access_ref, отключение с задачами (D-65)."""

import pytest
import pytest_asyncio
from catalog import DEMO, seed_workspaces
from harness_server.domain.errors import (
    NotFound,
    ProjectConflict,
    ProjectDisabled,
    UnknownWorkspace,
)
from harness_server.services import projects
from harness_server.services.tasks import change_status, create_task, get_task
from harness_shared.projects import (
    ProjectInput,
    ProjectRepo,
    ProjectStatus,
    ProjectUpdate,
    Workspace,
)
from harness_shared.tasks import TaskEventSource, TaskKind, TaskSource, TaskStatus
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

Factory = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture(loop_scope="session")
async def factory(committed_session_factory: Factory) -> Factory:
    return committed_session_factory


def _input(workspace: Workspace = DEMO) -> ProjectInput:
    return ProjectInput.model_validate(workspace.model_dump())


async def test_create_project_is_active_and_keeps_repo_block(factory: Factory) -> None:
    async with factory() as session:
        created = await projects.create_project(session, _input())

    assert created.status == ProjectStatus.ACTIVE
    assert created.repo.provider == "gitlab"
    assert created.repo.access_ref == "vault:demo/gitlab/main"
    assert created.voice_aliases == ["демо", "демо-проект"]


async def test_duplicate_id_is_conflict_and_existing_project_is_unchanged(factory: Factory) -> None:
    await seed_workspaces(factory, DEMO)
    other = DEMO.model_copy(update={"name": "Подмена"})

    async with factory() as session:
        with pytest.raises(ProjectConflict):
            await projects.create_project(session, _input(other))
    async with factory() as session:
        stored = await projects.get_project(session, "demo")

    assert stored.name == "Демо-проект"


async def test_access_ref_that_is_not_a_vault_link_is_rejected_without_value() -> None:
    raw = {
        "id": "demo",
        "name": "Demo",
        "repo": {
            "provider": "github",
            "project": "owner/demo",
            "access_ref": "github_pat_plain_secret_value",
        },
    }

    with pytest.raises(ValidationError) as info:
        ProjectInput.model_validate(raw)

    fields = {".".join(str(p) for p in e["loc"]) for e in info.value.errors(include_input=False)}
    assert "repo.access_ref" in fields
    assert "github_pat_plain_secret_value" not in str(info.value.errors(include_input=False))


async def test_access_ref_is_optional_for_anonymous_clone(factory: Factory) -> None:
    anonymous = Workspace(
        id="public",
        name="Публичный",
        repo=ProjectRepo(provider="github", project="owner/public"),
    )

    async with factory() as session:
        created = await projects.create_project(session, _input(anonymous))

    assert created.repo.access_ref is None


async def test_update_changes_only_given_fields(factory: Factory) -> None:
    await seed_workspaces(factory, DEMO)

    async with factory() as session:
        updated = await projects.update_project(
            session, "demo", ProjectUpdate(test_command="pytest -q")
        )

    assert updated.test_command == "pytest -q"
    assert updated.name == "Демо-проект"
    assert updated.repo.access_ref == "vault:demo/gitlab/main"


async def test_repo_block_replaces_whole_block_including_access_ref(factory: Factory) -> None:
    await seed_workspaces(factory, DEMO)

    async with factory() as session:
        updated = await projects.update_project(
            session,
            "demo",
            ProjectUpdate(repo=ProjectRepo(provider="gitlab", project="group/demo2")),
        )

    assert updated.repo.project == "group/demo2"
    assert updated.repo.access_ref is None


async def test_unknown_project_is_not_found(factory: Factory) -> None:
    async with factory() as session:
        with pytest.raises(NotFound):
            await projects.get_project(session, "missing")


async def test_disable_keeps_running_task_and_rejects_new_ones(factory: Factory) -> None:
    await seed_workspaces(factory, DEMO)
    async with factory() as session:
        running = await create_task(
            session,
            kind=TaskKind.IMPLEMENT,
            text="уже в работе",
            source=TaskSource.API,
            known_workspace_ids=["demo"],
            workspace_id="demo",
        )
        running = await change_status(
            session, running.id, TaskStatus.ACTIVE, source=TaskEventSource.API
        )

    async with factory() as session:
        disabled = await projects.disable_project(session, "demo")
    assert disabled.status == ProjectStatus.DISABLED

    async with factory() as session:
        # Задача в работе доходит до своего статуса: отключение её не меняет.
        assert (await get_task(session, running.id)).status == TaskStatus.ACTIVE
        # Новые задачи по проекту отклоняются сервисом проектов.
        with pytest.raises(ProjectDisabled):
            await projects.ensure_accepts_tasks(session, "demo")
        # Бот и API получают список известных проектов без отключённого.
        active = await projects.list_workspaces(session)
        assert "demo" not in [workspace.id for workspace in active]
        # Задача, принятая до отключения, находит свой проект любого статуса.
        assert (await projects.get_workspace(session, "demo")).id == "demo"


async def test_disabled_project_settings_are_not_issued(factory: Factory) -> None:
    await seed_workspaces(factory, DEMO)
    async with factory() as session:
        await projects.disable_project(session, "demo")

    async with factory() as session:
        with pytest.raises(ProjectDisabled):
            await projects.get_project_settings(session, "demo")


async def test_settings_contain_access_ref_link_only(factory: Factory) -> None:
    await seed_workspaces(factory, DEMO)

    async with factory() as session:
        settings = await projects.get_project_settings(session, "demo")

    dumped = settings.model_dump()
    assert dumped["repo"]["access_ref"] == "vault:demo/gitlab/main"
    assert "status" not in dumped and "updated_at" not in dumped


async def test_unknown_workspace_id_is_detected_by_create_task(factory: Factory) -> None:
    # id проверяет сервис задач по списку известных (активных) проектов.
    async with factory() as session:
        with pytest.raises(UnknownWorkspace):
            await create_task(
                session,
                kind=TaskKind.PLAN,
                text="в никуда",
                source=TaskSource.API,
                workspace_id="missing",
                known_workspace_ids=[],
            )
