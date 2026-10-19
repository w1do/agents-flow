"""Сервис песочниц: токены задач, подготовка песочницы, запуск и итог агента, очистка (mvp-06).

Публичные функции, которые работают с БД, — одна транзакция с commit (D-24). Долгие операции в
песочнице (exec, опрос агента) выполняются вне транзакции: их вызывает worker между коммитами.
Значения токенов, ключей и GITLAB_TOKEN в исключения и логи не попадают: в логах только
идентификаторы, роли и коды; текст из песочницы — только после redaction.
"""

import base64
import json
import logging
import shlex
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from harness_shared.sandboxes import AgentRole, SandboxStatus
from harness_shared.tasks import TaskEventSource, TaskKind, TaskStatus
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.adapters.novita import ExecResult, SandboxError, SandboxProvider
from harness_server.config import GitAuthorConfig, HarnessConfig, WorkspaceConfig
from harness_server.db.models import Sandbox, Task, TaskToken
from harness_server.domain.errors import UnknownWorkspace, UnsupportedKind
from harness_server.security import tokens
from harness_server.security.redaction import redact
from harness_server.services.agent_result import (
    LOG_TEXT_LIMIT,
    AgentRun,
    AgentState,
    parse_exit_code,
    parse_pid,
    parse_result,
    truncate_log_text,
)
from harness_server.services.tasks import get_task, lock_next_task

logger = logging.getLogger(__name__)

# Запас сверх лимита агента: токен не должен истечь раньше, чем агент отработает весь лимит (D-37).
TOKEN_EXPIRY_MARGIN: Final = timedelta(minutes=10)
# Скрипт кладётся в /tmp с уникальным именем на каждый запуск (D-52, ревью): envd пишет от root,
# а fs.protected_regular=2 не даёт открыть на запись существующий файл другого uid в sticky /tmp.
BOOTSTRAP_SCRIPT_PREFIX: Final = "/tmp/harness-bootstrap-"
# Клон и npm-установка медленные, но не должны висеть бесконечно: 15 минут.
BOOTSTRAP_TIMEOUT_SEC: Final = 900
# С памятью первый memory init индексирует проекты: без запаса по времени он оборвётся (D-47).
BOOTSTRAP_MEMORY_TIMEOUT_SEC: Final = 1800
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


def git_auth_header(token: str) -> str:
    """Заголовок Basic для git: oauth2:<token> в base64 (D-52). Значение — секрет."""
    basic = base64.b64encode(f"oauth2:{token}".encode()).decode("ascii")
    return f"Authorization: Basic {basic}"


def git_auth_env(base_url: str, token: str) -> dict[str, str]:
    """env git-команды: заголовок только для URL, начинающихся с base_url (D-52).

    GIT_CONFIG_* передаются через env, а не argv и не файлы; git сопоставляет http.<url>.*
    по префиксу
    URL, поэтому другой хост заголовка не получает. Требуется git >= 2.31 (Ubuntu 24.04 — 2.43).
    """
    prefix = f"{base_url.rstrip('/')}/"
    # Редиректы выключены, чтобы заголовок не ушёл на другой хост (D-52).
    return {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": f"http.{prefix}.extraHeader",
        "GIT_CONFIG_VALUE_0": git_auth_header(token),
        "GIT_CONFIG_KEY_1": "http.followRedirects",
        "GIT_CONFIG_VALUE_1": "false",
        "GIT_TERMINAL_PROMPT": "0",
    }


def git_author_env(author: GitAuthorConfig) -> dict[str, str]:
    """env агента для коммитов: автор и коммиттер из sandbox.git_author (env команды запуска, не файл)."""
    return {
        "GIT_AUTHOR_NAME": author.name,
        "GIT_AUTHOR_EMAIL": author.email,
        "GIT_COMMITTER_NAME": author.name,
        "GIT_COMMITTER_EMAIL": author.email,
    }


def git_auth_secret_values(token: str) -> tuple[str, str]:
    """Секреты заголовка для redaction: полная строка заголовка и bare base64 из неё (D-52)."""
    header = git_auth_header(token)
    return header, header.removeprefix("Authorization: Basic ")


async def _remove_bootstrap_script(provider: SandboxProvider, sandbox_id: str, path: str) -> None:
    """Удаляет временный скрипт bootstrap. Сбой rm не меняет исход, текст не логируется."""
    try:
        await provider.exec(sandbox_id, f"rm -f {shlex.quote(path)}", timeout_s=SHORT_TIMEOUT_SEC)
    except Exception as exc:
        logger.warning("bootstrap script cleanup failed type=%s", type(exc).__name__)


async def bootstrap(
    provider: SandboxProvider,
    sandbox_id: str,
    config: HarnessConfig,
    *,
    script: str,
    gitlab_token: SecretStr | None,
    memory_ref: str | None = None,
    memory_repo: str | None = None,
    embedding_key: SecretStr | None = None,
) -> ExecResult:
    """Подготавливает песочницу скриптом deploy/sandbox/bootstrap.sh (design 16, 3).

    Скрипт записывается в песочницу как есть и запускается с версиями и парами <id>=<url> из
    конфига. memory_ref — полный sha коммита memory-agent, memory_repo — его GitHub-репозиторий
    (D-51): задаются вместе, иначе ValueError до любого вызова провайдера. Тогда bootstrap ставит
    Docker и memory-agent и индексирует клоны (D-47). Ключи (GitLab и embeddings) передаются только
    в env этой команды: в скрипт и файлы они не попадают. Возвращает результат команды; код
    ненулевой — ответственность вызывающего (CLI). Вывод команды вызывающий должен пропустить через
    redaction, прежде чем показать.
    """
    if (memory_ref is None) != (memory_repo is None):
        raise ValueError("memory_ref и memory_repo задаются вместе")
    args = [
        "--claude-version",
        config.sandbox.claude_code_version,
        "--openspec-version",
        config.sandbox.openspec_version,
        "--git-name",
        config.sandbox.git_author.name,
        "--git-email",
        config.sandbox.git_author.email,
    ]
    # Токен GitLab уходит только на префикс базового адреса GitLab (D-52): заголовок строит скрипт.
    args += ["--gitlab-url", config.gitlab.base_url]
    if memory_ref is not None and memory_repo is not None:
        args += ["--memory-ref", memory_ref, "--memory-repo", memory_repo]
    args += [f"{ws.id}={clone_url(config, ws)}" for ws in config.workspaces]
    script_path = f"{BOOTSTRAP_SCRIPT_PREFIX}{uuid.uuid4().hex}.sh"
    command = shlex.join(["bash", script_path, *args])

    # GITLAB_TOKEN нужен скрипту, чтобы собрать заголовок git; скрипт снимает его из env сразу.
    # Без токена (публичные репозитории) переменной нет: клоны идут анонимно.
    # HARNESS_SANDBOX_BOOTSTRAP — защита скрипта от запуска вне песочницы (ревью, D-52).
    envs = {"GIT_TERMINAL_PROMPT": "0", "HARNESS_SANDBOX_BOOTSTRAP": "1"}
    if gitlab_token is not None:
        envs["GITLAB_TOKEN"] = gitlab_token.get_secret_value()
    if embedding_key is not None:
        envs["EMBEDDING_API_KEY"] = embedding_key.get_secret_value()
    # Память без таймаута памяти оборвёт первый memory init на большом проекте.
    timeout_s = BOOTSTRAP_TIMEOUT_SEC if memory_ref is None else BOOTSTRAP_MEMORY_TIMEOUT_SEC

    await provider.connect(sandbox_id)
    try:
        await provider.write_file(sandbox_id, script_path, script)
        result = await provider.exec(sandbox_id, command, envs=envs, timeout_s=timeout_s)
    finally:
        # Скрипт не остаётся в песочнице и при сбое записи или запуска (ревью, D-52).
        await _remove_bootstrap_script(provider, sandbox_id, script_path)
    logger.info("sandbox bootstrap finished sandbox=%s exit_code=%s", sandbox_id, result.exit_code)
    return result


# Таймаут exec для git и файловых команд: клон и fetch медленные, но не бесконечные.
GIT_TIMEOUT_SEC: Final = 300
SHORT_TIMEOUT_SEC: Final = 60
# Агент выполняется в фоне; после SIGTERM группе даётся 10 секунд до SIGKILL (design 3).
KILL_GRACE_SEC: Final = 10
# Сколько последних событий потока читается для итога хода (design 3).
STREAM_TAIL_LINES: Final = 200
# Хвост stderr читается байтами: символ UTF-8 занимает до 4 байт, поэтому запас по лимиту текста.
STDERR_TAIL_BYTES: Final = 4 * LOG_TEXT_LIMIT
CLAUDE_CODE_AGENT_TYPE: Final = "claude-code"


class SandboxStepError(Exception):
    """Шаг песочницы не выполнен. reason — машинная причина без текста команды и вывода."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"sandbox step failed: {reason}")
        self.reason = reason


class SandboxBusy(Exception):
    """За песочницей закреплена задача: пауза и возобновление отказывают (design 9, 4.2)."""

    def __init__(self, task_id: UUID) -> None:
        super().__init__(f"песочница занята задачей {task_id}")
        self.task_id = task_id


class CleanupFailed(Exception):
    """Очистка после задачи не удалась. Песочница в error, current_task_id оставлен для разбора."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"sandbox cleanup failed: {reason}")
        self.reason = reason


class AgentStartState(StrEnum):
    """Итог run_agent: запущен сейчас или уже был запущен раньше (идемпотентность, design 10).

    DIED — запуск записан на сервере, процесс мёртв, status.json нет (либо файлы есть без
    серверной записи): агент умер без итога. Повторно не запускается; итог выдаёт wait_agent
    (AgentState.DIED), а не «уже идёт».

    Вызывающий код на DIED обязан вызвать wait_agent, а не переводить задачу в error сразу: между
    проверками агент мог завершиться штатно, и wait_agent вернёт FINISHED (design 10).
    """

    STARTED = "started"
    ALREADY_RUNNING = "already_running"
    ALREADY_FINISHED = "already_finished"
    DIED = "died"


@dataclass(frozen=True, slots=True)
class AgentStart:
    """Результат run_agent. token есть только при фактическом запуске; после рестарта worker нет
    (D-37)."""

    state: AgentStartState
    token: SecretStr | None = None


@dataclass(frozen=True, slots=True)
class AgentRunInfo:
    """Серверная запись запуска агента: время и pid из БД, а не из файлов песочницы (D-41)."""

    started_at: datetime | None
    pid: int | None


@dataclass(frozen=True, slots=True)
class Reservation:
    """Песочница и задача, закреплённые одной транзакцией (design 9)."""

    provider_id: str
    task: Task


class QueuePipeline(Protocol):
    """Часть пайплайна, которую читает резервирование: какую задачу взять из очереди."""

    @property
    def kind(self) -> TaskKind: ...

    @property
    def from_status(self) -> TaskStatus: ...

    @property
    def to_status(self) -> TaskStatus | None: ...


def task_dir(home: str, task_id: UUID) -> str:
    """Каталог файлов задачи в песочнице: prompt.md, run.sh, run.json, pid, stream.jsonl,
    status.json."""
    return f"{home}/.harness/tasks/{task_id}"


def worktree_dir(home: str, task_id: UUID) -> str:
    """Worktree задачи: ~/.harness/worktrees/<task_id>."""
    return f"{home}/.harness/worktrees/{task_id}"


def workspace_for(config: HarnessConfig, task: Task) -> WorkspaceConfig:
    """Workspace задачи из конфига. Нет workspace или id неизвестен — UnknownWorkspace."""
    for workspace in config.workspaces:
        if workspace.id == task.workspace_id:
            return workspace
    raise UnknownWorkspace(str(task.workspace_id))


async def ensure_sandbox(session: AsyncSession, config: HarnessConfig) -> Sandbox:
    """Создаёт строку песочницы из конфига, если её нет (design 8). Существующую не меняет.

    Статус существующей строки не сбрасывается: активная песочница не должна стать paused.
    """
    provider_id = config.sandbox.provider_id
    row = (
        await session.execute(select(Sandbox).where(Sandbox.provider_id == provider_id))
    ).scalar_one_or_none()
    if row is None:
        row = Sandbox(
            provider_id=provider_id,
            agent_type=CLAUDE_CODE_AGENT_TYPE,
            status=SandboxStatus.PAUSED,
        )
        session.add(row)
        await session.commit()
        logger.info("sandbox created provider_id=%s", provider_id)
    return row


async def sandbox_status(session: AsyncSession, provider_id: str) -> Sandbox | None:
    """Строка песочницы по id провайдера; None, если её нет (ensure_sandbox не вызывали)."""
    result = await session.execute(select(Sandbox).where(Sandbox.provider_id == provider_id))
    return result.scalar_one_or_none()


async def _locked_sandbox(session: AsyncSession, provider_id: str) -> Sandbox:
    """Строка песочницы под FOR UPDATE. Нет строки — SandboxStepError: ensure_sandbox не
    вызывали."""
    result = await session.execute(
        select(Sandbox).where(Sandbox.provider_id == provider_id).with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise SandboxStepError("sandbox_not_registered")
    return row


async def agent_run_info(session: AsyncSession, provider_id: str) -> AgentRunInfo:
    """Время запуска и pid агента из строки песочницы. Нет строки — SandboxStepError.

    Транзакция завершается commit до возврата: exec с агентом идёт вне открытой транзакции (D-24).
    """
    row = await sandbox_status(session, provider_id)
    if row is None:
        raise SandboxStepError("sandbox_not_registered")
    info = AgentRunInfo(started_at=row.agent_started_at, pid=row.agent_pid)
    await session.commit()
    return info


async def record_agent_pid(session: AsyncSession, provider_id: str, pid: int) -> None:
    """Сохраняет pid агента: сразу после запуска или найденный в файле при восстановлении."""
    row = await _locked_sandbox(session, provider_id)
    row.agent_pid = pid
    await session.commit()


async def _record_agent_started(
    session: AsyncSession, provider_id: str, started_at: datetime
) -> None:
    """Время запуска пишется до команды: сбой после неё не теряет отсчёт таймаута (design 18)."""
    row = await _locked_sandbox(session, provider_id)
    row.agent_started_at = started_at
    row.agent_pid = None
    await session.commit()


async def reserve(session: AsyncSession, pipeline: QueuePipeline) -> Reservation | None:
    """Закрепляет свободную песочницу и задачу очереди одной транзакцией (design 9, D-24).

    Порядок: сначала песочница (FOR UPDATE SKIP LOCKED), затем задача через lock_next_task. Нет
    свободной песочницы или задачи — откат и None: задача остаётся в прежнем статусе.
    """
    sandbox = (
        await session.execute(
            select(Sandbox)
            .where(Sandbox.current_task_id.is_(None), Sandbox.status == SandboxStatus.PAUSED)
            .order_by(Sandbox.created_at, Sandbox.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if sandbox is None:
        await session.rollback()
        return None

    task = await lock_next_task(
        session,
        kind=pipeline.kind,
        from_status=pipeline.from_status,
        to_status=pipeline.to_status,
        source=TaskEventSource.WORKER,
    )
    if task is None:
        await session.rollback()
        return None

    sandbox.current_task_id = task.id
    sandbox.status = SandboxStatus.ACTIVE
    sandbox.agent_started_at = None
    sandbox.agent_pid = None
    await session.commit()
    logger.info("sandbox reserved provider_id=%s task=%s", sandbox.provider_id, task.id)
    return Reservation(provider_id=sandbox.provider_id, task=task)


async def home_dir(provider: SandboxProvider, provider_id: str) -> str:
    """Абсолютный домашний каталог песочницы: файловые вызовы не раскрывают ~ (публично для
    worker и CLI)."""
    result = await provider.exec(provider_id, 'printf %s "$HOME"', timeout_s=SHORT_TIMEOUT_SEC)
    home = result.stdout.strip()
    if result.exit_code != 0 or not home.startswith("/"):
        raise SandboxStepError("home")
    return home


async def _exec_ok(
    provider: SandboxProvider,
    provider_id: str,
    cmd: str,
    *,
    reason: str,
    envs: dict[str, str] | None = None,
    timeout_s: int = SHORT_TIMEOUT_SEC,
) -> ExecResult:
    """exec, после которого ненулевой код — SandboxStepError с reason (без вывода команды)."""
    result = await provider.exec(provider_id, cmd, envs=envs, timeout_s=timeout_s)
    if result.exit_code != 0:
        logger.warning(
            "sandbox step failed sandbox=%s reason=%s code=%s",
            provider_id,
            reason,
            result.exit_code,
        )
        raise SandboxStepError(reason)
    return result


async def activate(
    provider: SandboxProvider,
    provider_id: str,
    task: Task,
    *,
    base_ref: str,
    timeout_min: int,
    gitlab_token: SecretStr | None,
    gitlab_base_url: str | None = None,
    default_branch: str = "main",
    memory_envs: Mapping[str, str] | None = None,
) -> None:
    """Подключает песочницу, продлевает её жизнь, обновляет репозиторий и создаёт worktree (design
    10, 4).

    Идемпотентно: если worktree уже на ветке task/<id>, worktree add не выполняется. Токен GitLab
    передаётся только в env git-команд. Исключения — SandboxError (провайдер) или SandboxStepError.

    memory_envs не None — память проекта включена: после fetch индекс клона обновляется командой
    memory sync (D-47). Сбой этого шага не роняет задачу: пишется предупреждение без вывода.
    memory_envs задаёт env команды (ключ embeddings — только здесь, не в файлах).
    """
    if task.workspace_id is None:
        raise SandboxStepError("no_workspace")
    # Токен без адреса GitLab: заголовок некуда привязать, а без привязки токен не уходит никуда.
    # Ошибка до любого вызова провайдера (D-52, ревью).
    if gitlab_token is not None and gitlab_base_url is None:
        raise ValueError("gitlab_token задан без gitlab_base_url: заголовок некуда привязать")
    await provider.connect(provider_id)
    # Новосоздаваемая песочница Novita живёт по таймауту (D-19): продлеваем на лимит агента + запас.
    await provider.extend_timeout(provider_id, (timeout_min + 10) * 60)

    home = await home_dir(provider, provider_id)
    repo = f"{home}/work/{task.workspace_id}"
    worktree = worktree_dir(home, task.id)
    branch = f"task/{task.id}"
    # Заголовок только на префикс базового адреса GitLab (D-52). Без адреса заголовка нет:
    # fetch пойдёт анонимно и упадёт на приватном репозитории, токен никуда не уходит.
    # Без токена (публичный репозиторий) заголовка нет: fetch анонимный (D-52).
    if gitlab_token is not None and gitlab_base_url is not None:
        git_envs = git_auth_env(gitlab_base_url, gitlab_token.get_secret_value())
    else:
        git_envs = {"GIT_TERMINAL_PROMPT": "0"}
    await _exec_ok(
        provider,
        provider_id,
        f"git -C {shlex.quote(repo)} fetch origin",
        reason="fetch",
        envs=git_envs,
        timeout_s=GIT_TIMEOUT_SEC,
    )
    if memory_envs is not None:
        await _sync_memory(
            provider,
            provider_id,
            task,
            home=home,
            repo=repo,
            default_branch=default_branch,
            envs=memory_envs,
        )

    current = await provider.exec(
        provider_id,
        f"git -C {shlex.quote(worktree)} rev-parse --abbrev-ref HEAD",
        timeout_s=SHORT_TIMEOUT_SEC,
    )
    current_branch = current.stdout.strip()
    if current.exit_code == 0 and current_branch == branch:
        logger.info("worktree already active task=%s", task.id)
        return
    if current.exit_code == 0 and current_branch:
        # Каталог есть, но на другой ветке: это не наш worktree, перезаписывать его нельзя.
        raise SandboxStepError("worktree_branch")

    await _exec_ok(
        provider,
        provider_id,
        f"git -C {shlex.quote(repo)} worktree add -B {shlex.quote(branch)} "
        f"{shlex.quote(worktree)} {shlex.quote(base_ref)}",
        reason="worktree",
        timeout_s=GIT_TIMEOUT_SEC,
    )
    logger.info("worktree created task=%s base=%s", task.id, base_ref)


async def _sync_memory(
    provider: SandboxProvider,
    provider_id: str,
    task: Task,
    *,
    home: str,
    repo: str,
    default_branch: str,
    envs: Mapping[str, str],
) -> None:
    """Инкрементальное обновление индекса памяти клона (design 4, D-47).

    Индекс отражает origin/<default_branch>, а не изменения агента: клон переводится на тип
    default_branch. Маркер <id>.ready ставит bootstrap; без него память не настроена и шаг
    пропускается. Ненулевой код или ошибка провайдера — предупреждение, задача продолжается.
    """
    workspace = shlex.quote(repo)
    marker = shlex.quote(f"{home}/.harness/memory/{task.workspace_id}.ready")
    ensure_docker = shlex.quote(f"{home}/.harness/bin/ensure-docker.sh")
    cmd = (
        f"if [ -f {marker} ] && command -v memory >/dev/null; then "
        f"bash {ensure_docker} && "
        f"git -C {workspace} checkout --quiet --detach --force "
        f"{shlex.quote(f'origin/{default_branch}')} && "
        "memory service up && "
        f"memory sync --path {workspace}; "
        "fi"
    )
    try:
        result = await provider.exec(provider_id, cmd, envs=dict(envs), timeout_s=GIT_TIMEOUT_SEC)
    except SandboxError as exc:
        logger.warning("memory sync failed task=%s reason=%s", task.id, exc.reason)
        return
    if result.exit_code != 0:
        # Вывод memory не логируется: он может содержать пути и текст из репозитория.
        logger.warning("memory sync failed task=%s exit_code=%s", task.id, result.exit_code)


def _run_script(directory: str, worktree: str, max_turns: int) -> str:
    """Содержимое run.sh (design 4). Секретов нет: токены приходят в env команды запуска."""
    prompt = shlex.quote(f"{directory}/prompt.md")
    stream = shlex.quote(f"{directory}/stream.jsonl")
    stderr = shlex.quote(f"{directory}/stderr.log")
    status = shlex.quote(f"{directory}/status.json")
    tmp = shlex.quote(f"{directory}/status.tmp")
    # Промпт идёт через stdin, а не аргументом: текст задачи, начинающийся с «-», не разбирается
    # как флаг claude.
    return (
        "#!/usr/bin/env bash\n"
        "# Запуск агента в фоне. Переменные авторизации Anthropic сбрасываются (D-37).\n"
        "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN\n"
        f"cd {shlex.quote(worktree)} || exit 1\n"
        "claude -p --output-format stream-json --verbose "
        f"--max-turns {max_turns} --permission-mode bypassPermissions "
        '--strict-mcp-config --mcp-config "$HOME/.harness/mcp.json" --setting-sources user '
        f"< {prompt} > {stream} 2> {stderr}\n"
        "code=$?\n"
        f'printf \'{{"exit_code": %d, "finished_at": "%s"}}\\n\' "$code" '
        '"$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
        f"> {tmp} && mv {tmp} {status}\n"
    )


async def run_agent(
    session: AsyncSession,
    provider: SandboxProvider,
    provider_id: str,
    task: Task,
    *,
    prompt: str,
    max_turns: int,
    timeout_min: int,
    secret_key: SecretStr,
    oauth_token: SecretStr,
    agents_flow_url: str,
    now: datetime | None = None,
    extra_envs: Mapping[str, str] | None = None,
    memory_enabled: bool = False,
) -> AgentStart:
    """Запускает агента в фоне и сразу возвращается (design 3–6, 10, 18).

    Идемпотентно по серверной записи agent_started_at (D-41): запуск есть в БД — второй не делается.
    Файлы песочницы без серверной записи (status.json, pid) агента не запускают: итог DIED,
    повторного запуска нет. Токен задачи выдаётся непосредственно перед запуском (D-37). Креды
    передаются только в env команды запуска; в файлы попадают только prompt, run.json и run.sh без
    значений.

    extra_envs — дополнительные переменные команды запуска (место для MCP агента); встроенные
    переменные их перекрывают. memory_enabled — добавить HARNESS_MEMORY_PROJECT с путём клона:
    без памяти переменной нет, как и до mvp-память (D-47).
    """
    home = await home_dir(provider, provider_id)
    directory = task_dir(home, task.id)
    info = await agent_run_info(session, provider_id)
    if info.started_at is not None:
        # Запуск уже был. Pid берём из БД; если его нет (сбой между запуском и записью), из файла.
        pid = info.pid
        if pid is None:
            pid_text = await provider.read_file(provider_id, f"{directory}/pid")
            pid = parse_pid(pid_text) if pid_text is not None else None
            if pid is not None:
                await record_agent_pid(session, provider_id, pid)
        if pid is not None and await _is_alive(provider, provider_id, pid):
            return AgentStart(AgentStartState.ALREADY_RUNNING)
        if await provider.read_file(provider_id, f"{directory}/status.json") is not None:
            return AgentStart(AgentStartState.ALREADY_FINISHED)
        return AgentStart(AgentStartState.DIED)

    # Серверной записи нет, но файлы остались: их не доверяем и агента повторно не запускаем (D-41).
    leftovers = (
        await provider.read_file(provider_id, f"{directory}/status.json") is not None
        or await provider.read_file(provider_id, f"{directory}/pid") is not None
    )
    if leftovers:
        return AgentStart(AgentStartState.DIED)

    role = _ROLE_BY_KIND.get(task.kind)
    if role is None:
        raise UnsupportedKind(task.kind)
    started_at = now if now is not None else datetime.now(UTC)
    await _exec_ok(provider, provider_id, f"mkdir -p {shlex.quote(directory)}", reason="mkdir")
    await provider.write_file(provider_id, f"{directory}/prompt.md", prompt)
    # run.json только для разбора человеком: сервер его не читает (D-41).
    run_info = {
        "started_at": started_at.isoformat(),
        "max_turns": max_turns,
        "role": str(role),
        "task_id": str(task.id),
    }
    await provider.write_file(provider_id, f"{directory}/run.json", json.dumps(run_info))
    await provider.write_file(
        provider_id,
        f"{directory}/run.sh",
        _run_script(directory, worktree_dir(home, task.id), max_turns),
    )

    token = await issue_task_token(
        session,
        task.id,
        secret_key=secret_key.get_secret_value(),
        agent_run_timeout_min=timeout_min,
        now=started_at,
    )
    # Время запуска пишется до команды: сбой после неё не теряет отсчёт таймаута (D-41).
    await _record_agent_started(session, provider_id, started_at)
    # pid возвращается в stdout и сохраняется сервером; файл pid — запасной путь при восстановлении.
    launch = (
        f"setsid nohup bash {shlex.quote(f'{directory}/run.sh')} >/dev/null 2>&1 < /dev/null & "
        f'pid=$!; echo "$pid" > {shlex.quote(f"{directory}/pid")}; echo "$pid"'
    )
    launch_envs: dict[str, str] = dict(extra_envs or {})
    if memory_enabled:
        launch_envs["HARNESS_MEMORY_PROJECT"] = f"{home}/work/{task.workspace_id}"
    launch_envs.update(
        {
            "CLAUDE_CODE_OAUTH_TOKEN": oauth_token.get_secret_value(),
            "AGENTS_FLOW_TOKEN": token,
            "AGENTS_FLOW_URL": agents_flow_url,
        }
    )
    launched = await _exec_ok(
        provider,
        provider_id,
        launch,
        reason="launch",
        envs=launch_envs,
    )
    pid = parse_pid(launched.stdout)
    if pid is None:
        raise SandboxStepError("launch_pid")
    await record_agent_pid(session, provider_id, pid)
    logger.info("agent started task=%s", task.id)
    return AgentStart(AgentStartState.STARTED, token=SecretStr(token))


async def _is_alive(provider: SandboxProvider, provider_id: str, pid: int) -> bool:
    """Группа процессов агента жива: kill -0 -- -<pid> возвращает 0.

    Проверяется группа, а не сам pid: setsid делает run.sh лидером группы, и агент живёт в ней
    вместе со своими дочерними процессами (как и kill по таймауту, design 3).
    """
    if pid <= 1:
        # kill -0 -- -1 проверяет все процессы пользователя; такой pid из БД не должен дойти (N1).
        return False
    result = await provider.exec(provider_id, f"kill -0 -- -{pid}", timeout_s=SHORT_TIMEOUT_SEC)
    return result.exit_code == 0


async def _kill_group(provider: SandboxProvider, provider_id: str, pid: int) -> None:
    """SIGTERM группе процессов агента, через KILL_GRACE_SEC — SIGKILL (design 3, 13)."""
    if pid <= 1:
        return
    await provider.exec(
        provider_id,
        f"kill -TERM -- -{pid} 2>/dev/null; sleep {KILL_GRACE_SEC}; "
        f"kill -KILL -- -{pid} 2>/dev/null; true",
        timeout_s=KILL_GRACE_SEC + SHORT_TIMEOUT_SEC,
    )


async def wait_agent(
    provider: SandboxProvider,
    provider_id: str,
    task: Task,
    *,
    started_at: datetime | None,
    pid: int | None,
    timeout_min: int,
    now: datetime,
    secrets: Sequence[str],
) -> AgentRun:
    """Один опрос агента: состояние, итог хода, таймаут и пропажа процесса (design 10, 13, 14, 18).

    started_at и pid — из серверной записи (D-41); run.json и файл pid песочницы не читаются.
    Файлы песочницы — подсказка: status.json и событие result дают итог, но FINISHED наступает
    только когда группа процессов агента мертва. started_at None — агент не запускался: exec не
    делается.

    Вызывается циклом worker с интервалом AGENT_POLL_INTERVAL_SEC. Текст из песочницы проходит
    redaction с точными значениями secrets; в AgentRun попадает хвост stderr не длиннее 2000
    символов.
    """
    if started_at is None:
        return AgentRun(state=AgentState.DIED, reason="агент не запущен")
    home = await home_dir(provider, provider_id)
    directory = task_dir(home, task.id)

    # Хвост, а не файл целиком: stderr агента может быть большим (design 14).
    stderr_result = await provider.exec(
        provider_id,
        f"tail -c {STDERR_TAIL_BYTES} {shlex.quote(f'{directory}/stderr.log')} 2>/dev/null",
        timeout_s=SHORT_TIMEOUT_SEC,
    )
    stderr_text = stderr_result.stdout if stderr_result.exit_code == 0 else ""
    stderr_tail = truncate_log_text(redact(stderr_text, extra_values=secrets))
    tail = await provider.exec(
        provider_id,
        f"tail -n {STREAM_TAIL_LINES} {shlex.quote(f'{directory}/stream.jsonl')}",
        timeout_s=SHORT_TIMEOUT_SEC,
    )
    lines = redact(tail.stdout, extra_values=secrets).splitlines() if tail.exit_code == 0 else []
    result = parse_result(lines)

    # Группа жива — агент работает, даже если status.json уже записан: итог не доверяем, пока
    # процессы не завершились (D-41).
    if pid is not None and await _is_alive(provider, provider_id, pid):
        if now - started_at > timedelta(minutes=timeout_min):
            await _kill_group(provider, provider_id, pid)
            logger.warning("agent timed out task=%s", task.id)
            return AgentRun(
                state=AgentState.TIMED_OUT,
                result=result,
                reason="превышено время",
                stderr_tail=stderr_tail,
            )
        return AgentRun(state=AgentState.RUNNING)

    status_text = await provider.read_file(provider_id, f"{directory}/status.json")
    if status_text is not None:
        exit_code = parse_exit_code(status_text)
        reason = None if exit_code is not None else "статус не читается"
        return AgentRun(
            state=AgentState.FINISHED,
            exit_code=exit_code,
            result=result,
            reason=reason,
            stderr_tail=stderr_tail,
        )
    logger.warning("agent vanished without status task=%s", task.id)
    return AgentRun(
        state=AgentState.DIED,
        result=result,
        reason="агент завершился без статуса",
        stderr_tail=stderr_tail,
    )


async def cleanup_task(
    session: AsyncSession,
    provider: SandboxProvider,
    provider_id: str,
    task: Task,
    *,
    secrets: Sequence[str],
) -> None:
    """Очистка после задачи: worktree, локальная ветка, каталог задачи, отзыв токенов (design 12).

    Токены отзываются первым шагом: отзыв не зависит от исхода очистки (пункт B). Очистка
    идемпотентна: отсутствие worktree или ветки (активация упала до worktree add) — не ошибка.
    Ненулевой код любой команды — песочница в error, current_task_id сохраняется, CleanupFailed.
    Причина в лог проходит redaction.
    """
    await revoke_task_tokens(session, task.id)
    # Агент мог запуститься до сбоя (например, БД упала после launch): его группа должна умереть
    # до удаления каталога и worktree. Живость проверяется до kill: у мёртвой группы _kill_group
    # ждал бы KILL_GRACE_SEC впустую.
    row = await sandbox_status(session, provider_id)
    pid = row.agent_pid if row is not None else None
    if pid is not None and await _is_alive(provider, provider_id, pid):
        await _kill_group(provider, provider_id, pid)
    home = await home_dir(provider, provider_id)
    commands: list[str] = []
    if task.workspace_id is not None:
        repo = shlex.quote(f"{home}/work/{task.workspace_id}")
        worktree = shlex.quote(worktree_dir(home, task.id))
        branch = f"task/{task.id}"
        commands += [
            # worktree remove на отсутствующем каталоге падает; тогда допустим только отсутствующий
            # каталог, и stale-запись убирает prune.
            f"git -C {repo} worktree remove --force {worktree} "
            f"|| {{ [ ! -e {worktree} ] && git -C {repo} worktree prune; }}",
            # branch -D на отсутствующей ветке падает; тогда допустимо только её отсутствие.
            f"git -C {repo} branch -D {shlex.quote(branch)} "
            f"|| ! git -C {repo} show-ref --verify --quiet {shlex.quote(f'refs/heads/{branch}')}",
        ]
    # Каталог задачи удаляется всегда, даже без workspace: активация могла упасть до git
    # (design 12).
    commands.append(f"rm -rf {shlex.quote(task_dir(home, task.id))}")
    for cmd in commands:
        result = await provider.exec(provider_id, cmd, timeout_s=GIT_TIMEOUT_SEC)
        if result.exit_code != 0:
            detail = truncate_log_text(redact(result.stderr, extra_values=secrets))
            logger.error(
                "sandbox cleanup failed sandbox=%s task=%s code=%s stderr=%s",
                provider_id,
                task.id,
                result.exit_code,
                detail,
            )
            row = await _locked_sandbox(session, provider_id)
            row.status = SandboxStatus.ERROR
            await session.commit()
            raise CleanupFailed("command")
    logger.info("task cleanup done task=%s", task.id)


async def release_sandbox(
    session: AsyncSession, provider: SandboxProvider, provider_id: str
) -> None:
    """Пауза после успешной очистки и освобождение песочницы (design 12).

    Ошибка паузы переводит песочницу в error; current_task_id остаётся для разбора.
    """
    row = await _locked_sandbox(session, provider_id)
    try:
        await provider.pause(provider_id)
    except SandboxError:
        row.status = SandboxStatus.ERROR
        await session.commit()
        raise
    row.current_task_id = None
    row.status = SandboxStatus.PAUSED
    row.agent_started_at = None
    row.agent_pid = None
    await session.commit()
    logger.info("sandbox released provider_id=%s", provider_id)


async def assert_not_busy(session: AsyncSession, provider_id: str) -> None:
    """Отказ SandboxBusy, если за песочницей закреплена задача. Нет строки — не занята.

    Для bootstrap: скрипт меняет окружение, которым пользуется активная задача (пункт I).
    Блокировки нет: проверка защищает от типичной ошибки оператора, не от гонки.
    """
    row = await sandbox_status(session, provider_id)
    if row is not None and row.current_task_id is not None:
        raise SandboxBusy(row.current_task_id)


async def pause_sandbox(session: AsyncSession, provider: SandboxProvider, provider_id: str) -> None:
    """Ручная пауза (CLI). Отказывает, если за песочницей закреплена задача (SandboxBusy)."""
    row = await _locked_sandbox(session, provider_id)
    if row.current_task_id is not None:
        raise SandboxBusy(row.current_task_id)
    await provider.pause(provider_id)
    row.status = SandboxStatus.PAUSED
    await session.commit()
    logger.info("sandbox paused by operator provider_id=%s", provider_id)


async def resume_sandbox(
    session: AsyncSession, provider: SandboxProvider, provider_id: str
) -> None:
    """Возобновление (CLI) по статусу строки (design 8).

    Закреплена задача — SandboxBusy до любых вызовов провайдера: такая задача требует разбора, а
    current_task_id здесь не сбрасывается (design 12). paused без задачи — пустая операция: лишний
    connect разбудил бы песочницу. error или active без задачи (рассинхрон) — connect, pause, статус
    paused и обнуление колонок агента; ошибка провайдера пробрасывается, строка не меняется.
    """
    row = await _locked_sandbox(session, provider_id)
    if row.current_task_id is not None:
        raise SandboxBusy(row.current_task_id)
    if row.status == SandboxStatus.PAUSED:
        logger.info("sandbox resume skipped: already paused provider_id=%s", provider_id)
        await session.commit()
        return
    if row.status == SandboxStatus.ACTIVE:
        logger.warning("sandbox desync: active without task provider_id=%s", provider_id)
    await provider.connect(provider_id)
    await provider.pause(provider_id)
    row.status = SandboxStatus.PAUSED
    row.agent_started_at = None
    row.agent_pid = None
    await session.commit()
    logger.info("sandbox resumed provider_id=%s", provider_id)
