"""Сервис песочниц: токены задач и подготовка песочницы (mvp-06, часть A).

Публичные функции, которые работают с БД, — одна транзакция с commit (D-24). bootstrap БД не
трогает. Значения токенов, ключей и GITLAB_TOKEN в исключения и логи не попадают: в логах только
идентификаторы, роли и коды.
"""

import logging
import shlex
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from harness_shared.sandboxes import AgentRole
from harness_shared.tasks import TaskKind
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.adapters.novita import ExecResult, SandboxProvider
from harness_server.config import HarnessConfig, WorkspaceConfig
from harness_server.db.models import TaskToken
from harness_server.domain.errors import UnsupportedKind
from harness_server.security import tokens
from harness_server.services.tasks import get_task

logger = logging.getLogger(__name__)

# Запас сверх лимита агента: токен не должен истечь раньше, чем агент отработает весь лимит (D-37).
TOKEN_EXPIRY_MARGIN: Final = timedelta(minutes=10)
# Скрипт кладётся в /tmp: путь абсолютный, поэтому не зависит от домашнего каталога песочницы.
BOOTSTRAP_SCRIPT_PATH: Final = "/tmp/harness-bootstrap.sh"
# Клон и npm-установка медленные, но не должны висеть бесконечно: 15 минут.
BOOTSTRAP_TIMEOUT_SEC: Final = 900
# Роль агента по типу задачи (design 7): план — planner, реализация — implementer.
_ROLE_BY_KIND: Final = {
    TaskKind.PLAN: AgentRole.PLANNER,
    TaskKind.IMPLEMENT: AgentRole.IMPLEMENTER,
}


async def issue_task_token(
    session: AsyncSession,
    task_id: UUID,
    *,
    secret_key: str,
    agent_run_timeout_min: int,
    now: datetime | None = None,
) -> str:
    """Выдаёт токен агента для задачи. В БД пишется только HMAC-хеш; значение возвращается один раз.

    Роль берётся из kind задачи. Бросает NotFound (задачи нет) и UnsupportedKind (kind без роли,
    например check в MVP) — до записи. Токен выдаётся непосредственно перед запуском агента, а не
    при активации: после рестарта worker значение уже не восстановить (D-37).
    """
    task = await get_task(session, task_id)
    role = _ROLE_BY_KIND.get(task.kind)
    if role is None:
        raise UnsupportedKind(task.kind)

    issued_at = now if now is not None else datetime.now(UTC)
    token = tokens.generate()
    session.add(
        TaskToken(
            task_id=task.id,
            token_hash=tokens.hash_token(token, secret_key),
            role=role,
            expires_at=issued_at + timedelta(minutes=agent_run_timeout_min) + TOKEN_EXPIRY_MARGIN,
        )
    )
    await session.commit()
    logger.info("task token issued task=%s role=%s", task.id, role)
    return token


async def revoke_task_tokens(
    session: AsyncSession, task_id: UUID, *, now: datetime | None = None
) -> None:
    """Отзывает все ещё не отозванные токены задачи: ставит revoked_at.

    Уже отозванные строки не трогаются, повторный вызов безопасен. Проверка токена на стороне MCP —
    mvp-07; здесь только запись отзыва.
    """
    revoked_at = now if now is not None else datetime.now(UTC)
    await session.execute(
        update(TaskToken)
        .where(TaskToken.task_id == task_id, TaskToken.revoked_at.is_(None))
        .values(revoked_at=revoked_at)
    )
    await session.commit()
    logger.info("task tokens revoked task=%s", task_id)


def clone_url(config: HarnessConfig, workspace: WorkspaceConfig) -> str:
    """Адрес клона репозитория workspace: base_url GitLab + проект. Учётных данных в адресе нет."""
    return f"{config.gitlab.base_url.rstrip('/')}/{workspace.gitlab_project}.git"


async def bootstrap(
    provider: SandboxProvider,
    sandbox_id: str,
    config: HarnessConfig,
    *,
    script: str,
    gitlab_token: SecretStr,
) -> ExecResult:
    """Подготавливает песочницу скриптом deploy/sandbox/bootstrap.sh (design 16).

    Скрипт записывается в песочницу как есть и запускается с версиями и парами <id>=<url> из
    конфига. Токен GitLab передаётся только в env этой команды: в скрипт и файлы он не попадает.
    Возвращает результат команды; код ненулевой — ответственность вызывающего (CLI). Вывод команды
    вызывающий должен пропустить через redaction, прежде чем показать.
    """
    args = [
        "--claude-version",
        config.sandbox.claude_code_version,
        "--openspec-version",
        config.sandbox.openspec_version,
        *(f"{ws.id}={clone_url(config, ws)}" for ws in config.workspaces),
    ]
    command = shlex.join(["bash", BOOTSTRAP_SCRIPT_PATH, *args])

    await provider.connect(sandbox_id)
    await provider.write_file(sandbox_id, BOOTSTRAP_SCRIPT_PATH, script)
    result = await provider.exec(
        sandbox_id,
        command,
        envs={"GITLAB_TOKEN": gitlab_token.get_secret_value(), "GIT_TERMINAL_PROMPT": "0"},
        timeout_s=BOOTSTRAP_TIMEOUT_SEC,
    )
    logger.info("sandbox bootstrap finished sandbox=%s exit_code=%s", sandbox_id, result.exit_code)
    return result
