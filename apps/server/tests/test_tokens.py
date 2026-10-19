"""Токены задач: генерация, HMAC-хеш и выдача/отзыв через сервис на Postgres (mvp-06, 3.1)."""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from harness_server.db.models import TaskToken
from harness_server.domain.errors import NotFound
from harness_server.security import tokens
from harness_server.services.sandboxes import issue_task_token, revoke_task_tokens
from harness_server.services.tasks import create_task
from harness_shared.sandboxes import AgentRole
from harness_shared.tasks import TaskKind, TaskSource
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Тестовое значение длиной не короче 32 символов; настоящий ключ здесь не используется.
KEY = "test-secret-key-0123456789abcdef0123"
OTHER_KEY = "other-secret-key-0123456789abcdef0123"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def test_generated_tokens_are_random_and_url_safe() -> None:
    first = tokens.generate()
    second = tokens.generate()

    assert first != second
    assert len(first) >= 40
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)


def test_hash_is_hex_hmac_and_depends_on_key() -> None:
    token = tokens.generate()

    digest = tokens.hash_token(token, KEY)

    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest == tokens.hash_token(token, KEY)
    assert digest != tokens.hash_token(token, OTHER_KEY)
    assert token not in digest


async def _task_id(session: AsyncSession, kind: TaskKind = TaskKind.IMPLEMENT) -> UUID:
    task = await create_task(
        session,
        kind=kind,
        text="задача для токена",
        source=TaskSource.API,
        known_workspace_ids=[],
    )
    return task.id


async def _rows(session: AsyncSession, task_id: UUID) -> list[TaskToken]:
    result = await session.execute(select(TaskToken).where(TaskToken.task_id == task_id))
    return list(result.scalars().all())


@pytest.mark.asyncio(loop_scope="session")
async def test_issue_stores_only_hash_with_expiry(db_session: AsyncSession) -> None:
    task_id = await _task_id(db_session)

    token = await issue_task_token(
        db_session, task_id, secret_key=KEY, agent_run_timeout_min=60, now=NOW
    )

    [row] = await _rows(db_session, task_id)
    assert row.token_hash == tokens.hash_token(token, KEY)
    assert row.role == AgentRole.IMPLEMENTER
    # Срок: лимит агента плюс запас 10 минут (D-37).
    assert row.expires_at == NOW + timedelta(minutes=70)
    assert row.revoked_at is None
    # Значение токена не попадает ни в одну колонку строки.
    assert all(
        token not in str(getattr(row, column.name)) for column in TaskToken.__table__.columns
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_plan_task_gets_planner_role(db_session: AsyncSession) -> None:
    task_id = await _task_id(db_session, TaskKind.PLAN)

    await issue_task_token(db_session, task_id, secret_key=KEY, agent_run_timeout_min=60, now=NOW)

    [row] = await _rows(db_session, task_id)
    assert row.role == AgentRole.PLANNER


@pytest.mark.asyncio(loop_scope="session")
async def test_issue_for_unknown_task_is_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFound):
        await issue_task_token(
            db_session, uuid4(), secret_key=KEY, agent_run_timeout_min=60, now=NOW
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_revoke_sets_revoked_at_once_per_token(db_session: AsyncSession) -> None:
    task_id = await _task_id(db_session)
    await issue_task_token(db_session, task_id, secret_key=KEY, agent_run_timeout_min=60, now=NOW)

    first_revoke = NOW + timedelta(minutes=1)
    await revoke_task_tokens(db_session, task_id, now=first_revoke)
    # Другой момент выдачи: срок второго токена больше, и порядок строк детерминирован.
    await issue_task_token(
        db_session,
        task_id,
        secret_key=KEY,
        agent_run_timeout_min=60,
        now=NOW + timedelta(minutes=5),
    )
    second_revoke = NOW + timedelta(minutes=2)
    await revoke_task_tokens(db_session, task_id, now=second_revoke)

    revoked = sorted(row.revoked_at for row in await _rows(db_session, task_id) if row.revoked_at)
    assert revoked == [first_revoke, second_revoke]
    # Уже отозванный токен не перезаписывается: первая метка времени сохраняется.
    [first, second] = sorted(await _rows(db_session, task_id), key=lambda row: row.expires_at)
    assert first.revoked_at == first_revoke
    assert second.revoked_at == second_revoke
