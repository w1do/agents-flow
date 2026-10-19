"""Сервис песочниц: токены задач, подготовка песочницы, запуск и итог агента, очистка (mvp-06).

Публичные функции, которые работают с БД, — одна транзакция с commit (D-24). Долгие операции в
песочнице (exec, опрос агента) выполняются вне транзакции: их вызывает worker между коммитами.
Значения токенов, ключей и GITLAB_TOKEN в исключения и логи не попадают: в логах только
идентификаторы, роли и коды; текст из песочницы — только после redaction.
"""

import json
import logging
import shlex
from collections.abc import Sequence
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
from harness_server.config import HarnessConfig, WorkspaceConfig
from harness_server.db.models import Sandbox, Task, TaskToken
from harness_server.domain.errors import UnknownWorkspace, UnsupportedKind
from harness_server.security import tokens
from harness_server.security.redaction import redact
from harness_server.services.agent_result import (
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


# Таймаут exec для git и файловых команд: клон и fetch медленные, но не бесконечные.
GIT_TIMEOUT_SEC: Final = 300
SHORT_TIMEOUT_SEC: Final = 60
# Агент выполняется в фоне; после SIGTERM группе даётся 10 секунд до SIGKILL (design 3).
KILL_GRACE_SEC: Final = 10
# Сколько последних событий потока читается для итога хода (design 3).
STREAM_TAIL_LINES: Final = 200
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
    """Итог run_agent: запущен сейчас или уже был запущен раньше (идемпотентность, design 10)."""

    STARTED = "started"
    ALREADY_RUNNING = "already_running"
    ALREADY_FINISHED = "already_finished"


@dataclass(frozen=True, slots=True)
class AgentStart:
    """Результат run_agent. token есть только при фактическом запуске; после рестарта worker нет
    (D-37)."""

    state: AgentStartState
    token: SecretStr | None = None


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
    await session.commit()
    logger.info("sandbox reserved provider_id=%s task=%s", sandbox.provider_id, task.id)
    return Reservation(provider_id=sandbox.provider_id, task=task)


async def _home(provider: SandboxProvider, provider_id: str) -> str:
    """Абсолютный домашний каталог песочницы: файловые вызовы не раскрывают ~."""
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
    gitlab_token: SecretStr,
) -> None:
    """Подключает песочницу, продлевает её жизнь, обновляет репозиторий и создаёт worktree (design
    10).

    Идемпотентно: если worktree уже на ветке task/<id>, worktree add не выполняется. Токен GitLab
    передаётся только в env git-команд. Исключения — SandboxError (провайдер) или SandboxStepError.
    """
    if task.workspace_id is None:
        raise SandboxStepError("no_workspace")
    await provider.connect(provider_id)
    # Новосоздаваемая песочница Novita живёт по таймауту (D-19): продлеваем на лимит агента + запас.
    await provider.extend_timeout(provider_id, (timeout_min + 10) * 60)

    home = await _home(provider, provider_id)
    repo = f"{home}/work/{task.workspace_id}"
    worktree = worktree_dir(home, task.id)
    branch = f"task/{task.id}"
    git_envs = {
        "GITLAB_TOKEN": gitlab_token.get_secret_value(),
        "GIT_ASKPASS": f"{home}/.harness/bin/git-askpass.sh",
        "GIT_TERMINAL_PROMPT": "0",
    }
    await _exec_ok(
        provider,
        provider_id,
        f"git -C {shlex.quote(repo)} fetch origin",
        reason="fetch",
        envs=git_envs,
        timeout_s=GIT_TIMEOUT_SEC,
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


def _run_script(directory: str, worktree: str, max_turns: int) -> str:
    """Содержимое run.sh (design 4). Секретов нет: токены приходят в env команды запуска."""
    prompt = shlex.quote(f"{directory}/prompt.md")
    stream = shlex.quote(f"{directory}/stream.jsonl")
    stderr = shlex.quote(f"{directory}/stderr.log")
    status = shlex.quote(f"{directory}/status.json")
    tmp = shlex.quote(f"{directory}/status.tmp")
    return (
        "#!/usr/bin/env bash\n"
        "# Запуск агента в фоне. Переменные авторизации Anthropic сбрасываются (D-37).\n"
        "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN\n"
        f"cd {shlex.quote(worktree)} || exit 1\n"
        f'claude -p "$(cat {prompt})" --output-format stream-json --verbose '
        f"--max-turns {max_turns} --permission-mode bypassPermissions "
        '--strict-mcp-config --mcp-config "$HOME/.harness/mcp.json" --setting-sources user '
        f"> {stream} 2> {stderr}\n"
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
) -> AgentStart:
    """Запускает агента в фоне и сразу возвращается (design 3–6, 10).

    Идемпотентно: есть status.json — уже завершён; есть pid — уже запущен; второй запуск не
    делается.
    Токен задачи выдаётся непосредственно перед запуском (D-37). Креды передаются только в env
    команды запуска; в файлы попадают только prompt, run.json и run.sh без значений.
    """
    home = await _home(provider, provider_id)
    directory = task_dir(home, task.id)
    if await provider.read_file(provider_id, f"{directory}/status.json") is not None:
        return AgentStart(AgentStartState.ALREADY_FINISHED)
    if await provider.read_file(provider_id, f"{directory}/pid") is not None:
        return AgentStart(AgentStartState.ALREADY_RUNNING)

    started_at = now if now is not None else datetime.now(UTC)
    await _exec_ok(provider, provider_id, f"mkdir -p {shlex.quote(directory)}", reason="mkdir")
    await provider.write_file(provider_id, f"{directory}/prompt.md", prompt)
    run_info = {
        "started_at": started_at.isoformat(),
        "max_turns": max_turns,
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
    launch = (
        f"setsid nohup bash {shlex.quote(f'{directory}/run.sh')} >/dev/null 2>&1 < /dev/null & "
        f"echo $! > {shlex.quote(f'{directory}/pid')}"
    )
    await _exec_ok(
        provider,
        provider_id,
        launch,
        reason="launch",
        envs={
            "CLAUDE_CODE_OAUTH_TOKEN": oauth_token.get_secret_value(),
            "AGENTS_FLOW_TOKEN": token,
            "AGENTS_FLOW_URL": agents_flow_url,
        },
    )
    logger.info("agent started task=%s", task.id)
    return AgentStart(AgentStartState.STARTED, token=SecretStr(token))


async def _is_alive(provider: SandboxProvider, provider_id: str, pid: int) -> bool:
    """Процесс с pid жив: kill -0 возвращает 0."""
    result = await provider.exec(provider_id, f"kill -0 {pid}", timeout_s=SHORT_TIMEOUT_SEC)
    return result.exit_code == 0


async def _kill_group(provider: SandboxProvider, provider_id: str, pid: int) -> None:
    """SIGTERM группе процессов агента, через KILL_GRACE_SEC — SIGKILL (design 3, 13)."""
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
    timeout_min: int,
    now: datetime,
    secrets: Sequence[str],
) -> AgentRun:
    """Один опрос агента: статус, итог хода, таймаут и пропажа процесса (design 10, 13, 14).

    Вызывается циклом worker с интервалом AGENT_POLL_INTERVAL_SEC. Текст из песочницы проходит
    redaction с точными значениями secrets; в AgentRun попадает хвост stderr не длиннее 2000
    символов.
    """
    home = await _home(provider, provider_id)
    directory = task_dir(home, task.id)
    run_text = await provider.read_file(provider_id, f"{directory}/run.json")
    if run_text is None:
        return AgentRun(state=AgentState.DIED, reason="агент не запущен")
    started_at = _parse_started_at(run_text)

    stderr_text = await provider.read_file(provider_id, f"{directory}/stderr.log") or ""
    stderr_tail = truncate_log_text(redact(stderr_text, extra_values=secrets))
    tail = await provider.exec(
        provider_id,
        f"tail -n {STREAM_TAIL_LINES} {shlex.quote(f'{directory}/stream.jsonl')}",
        timeout_s=SHORT_TIMEOUT_SEC,
    )
    lines = redact(tail.stdout, extra_values=secrets).splitlines() if tail.exit_code == 0 else []
    result = parse_result(lines)

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

    pid_text = await provider.read_file(provider_id, f"{directory}/pid")
    pid = parse_pid(pid_text) if pid_text is not None else None
    if now - started_at > timedelta(minutes=timeout_min):
        if pid is not None:
            await _kill_group(provider, provider_id, pid)
        logger.warning("agent timed out task=%s", task.id)
        return AgentRun(
            state=AgentState.TIMED_OUT,
            result=result,
            reason="превышено время",
            stderr_tail=stderr_tail,
        )
    if pid is not None and await _is_alive(provider, provider_id, pid):
        return AgentRun(state=AgentState.RUNNING)
    logger.warning("agent vanished without status task=%s", task.id)
    return AgentRun(
        state=AgentState.DIED,
        result=result,
        reason="агент завершился без статуса",
        stderr_tail=stderr_tail,
    )


def _parse_started_at(run_text: str) -> datetime:
    """started_at из run.json. Битый файл — SandboxStepError: время таймаута неизвестно."""
    try:
        value = json.loads(run_text)["started_at"]
        started = datetime.fromisoformat(value)
    except (ValueError, KeyError, TypeError):
        raise SandboxStepError("run_json") from None
    if started.tzinfo is None:
        raise SandboxStepError("run_json")
    return started


async def cleanup_task(
    session: AsyncSession,
    provider: SandboxProvider,
    provider_id: str,
    task: Task,
    *,
    secrets: Sequence[str],
) -> None:
    """Очистка после задачи: worktree, локальная ветка, каталог задачи, отзыв токенов (design 12).

    Ненулевой код любой команды — песочница в error, current_task_id сохраняется, CleanupFailed.
    Причина в лог проходит redaction. Успех — токены задачи отозваны (revoke_task_tokens).
    """
    if task.workspace_id is not None:
        home = await _home(provider, provider_id)
        repo = f"{home}/work/{task.workspace_id}"
        commands = (
            f"git -C {shlex.quote(repo)} worktree remove --force "
            f"{shlex.quote(worktree_dir(home, task.id))}",
            f"git -C {shlex.quote(repo)} branch -D {shlex.quote(f'task/{task.id}')}",
            f"rm -rf {shlex.quote(task_dir(home, task.id))}",
        )
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
    await revoke_task_tokens(session, task.id)
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
    await session.commit()
    logger.info("sandbox released provider_id=%s", provider_id)


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
    """Возобновление (CLI): connect, затем статус paused. error с закреплённой задачей не
    сбрасывается.

    Такая задача требует разбора; сброс current_task_id вручную здесь не делается (design 8, 12).
    """
    row = await _locked_sandbox(session, provider_id)
    if row.current_task_id is not None:
        raise SandboxBusy(row.current_task_id)
    await provider.connect(provider_id)
    row.status = SandboxStatus.PAUSED
    await session.commit()
    logger.info("sandbox resumed provider_id=%s", provider_id)
