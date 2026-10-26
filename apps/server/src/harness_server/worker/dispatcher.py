"""Диспетчер песочницы: восстановление → reserve → activate → run → cleanup → pause (mvp-06, design
11–12).

Каждый шаг с БД — отдельная короткая транзакция в сервисе; exec и опрос агента идут между ними, без
открытой транзакции. Ошибка пайплайна, исключение или таймаут переводят задачу в error (если переход
разрешён таблицей) с причиной; очистка и пауза выполняются в любом случае, кроме ошибки очистки.
Часы и пауза между опросами инъецируются: тесты не ждут реального времени.
Отмена worker (BaseException) очистку не выполняет и токены задачи не отзывает (D-41).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from harness_shared.sandboxes import SandboxStatus
from harness_shared.tasks import TaskEventSource, TaskKind, TaskStatus
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harness_server.adapters.sandbox import SandboxError, SandboxProvider
from harness_server.adapters.vault import SecretVault, VaultError
from harness_server.config import HarnessConfig
from harness_server.db.models import Sandbox, Task
from harness_server.domain.statuses import allowed_transitions
from harness_server.security.redaction import redact
from harness_server.services import git_access, sandboxes
from harness_server.services import secrets as secret_refs
from harness_server.services.agent_result import AgentRun, AgentState, truncate_log_text
from harness_server.services.sandboxes import (
    AgentStart,
    CleanupFailed,
    Reservation,
    SandboxStepError,
)
from harness_server.services.tasks import add_event, change_status, get_task
from harness_server.settings import Settings
from harness_server.wiring import build_vault, secret_values
from harness_server.worker.pipeline import PIPELINES, Outcome, Pipeline

logger = logging.getLogger(__name__)

# Пауза между опросами агента, если не задана ENV: совпадает с AGENT_POLL_INTERVAL_SEC по умолчанию.
DEFAULT_AGENT_POLL_INTERVAL_SEC: Final = 15.0
# Задача без ключа записи в error до активации песочницы: все пайплайны пушат ветку (D-60).
REPO_ACCESS_REF_REASON: Final = (
    "repo_access_ref: у workspace {workspace_id} нет repo.access_ref — "
    "задаче нужен ключ записи (push)"
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """Всё, что диспетчеру нужно для работы с песочницей. Секреты — SecretStr; secrets — их
    значения."""

    provider: SandboxProvider
    config: HarnessConfig
    session_factory: async_sessionmaker[AsyncSession]
    oauth_token: SecretStr
    secret_key: SecretStr
    agents_flow_url: str
    timeout_min: int
    poll_interval_sec: float
    # Значения всех секретов для redaction текста из песочницы и ошибок (design 14).
    secrets: tuple[str, ...] = field(default=())
    # Vault для ссылок vault:… (access_ref проектов, memory); None без VAULT_MCP_URL/TOKEN.
    vault: SecretVault | None = None
    clock: Callable[[], datetime] = _utc_now
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


class _Runner:
    """AgentRunner для одного шага: держит песочницу, задачу и накопленные секреты текущего
    запуска."""

    def __init__(
        self, ctx: DispatchContext, pipeline: Pipeline, provider_id: str, task: Task
    ) -> None:
        self._ctx = ctx
        self._pipeline = pipeline
        self._provider_id = provider_id
        self._task = task
        self.secrets: tuple[str, ...] = ctx.secrets

    async def run_agent(self, prompt: str) -> AgentStart:
        async with self._ctx.session_factory() as session:
            workspace = await sandboxes.workspace_for(session, self._task)
            start = await sandboxes.run_agent(
                session,
                self._ctx.provider,
                self._provider_id,
                self._task,
                prompt=prompt,
                max_turns=workspace.agent_max_turns,
                timeout_min=self._ctx.timeout_min,
                secret_key=self._ctx.secret_key,
                oauth_token=self._ctx.oauth_token,
                agents_flow_url=self._ctx.agents_flow_url,
                now=self._ctx.clock(),
                extra_envs=sandboxes.git_author_env(self._ctx.config.sandbox.git_author),
                memory_enabled=self._ctx.config.sandbox.memory is not None,
            )
        if start.token is not None:
            # Значение токена известно только в этом процессе: после рестарта redaction его не
            # покроет.
            self.secrets = (*self.secrets, start.token.get_secret_value())
        return start

    async def wait_agent(self) -> AgentRun:
        while True:
            # Время и pid читаются из БД на каждом опросе: после рестарта worker они те же (D-41).
            async with self._ctx.session_factory() as session:
                info = await sandboxes.agent_run_info(session, self._provider_id)
            run = await sandboxes.wait_agent(
                self._ctx.provider,
                self._provider_id,
                self._task,
                started_at=info.started_at,
                pid=info.pid,
                timeout_min=self._ctx.timeout_min,
                now=self._ctx.clock(),
                secrets=self.secrets,
            )
            if run.state is not AgentState.RUNNING:
                break
            await self._ctx.sleep(self._ctx.poll_interval_sec)
        await self._report(run)
        return run

    async def _report(self, run: AgentRun) -> None:
        """Пишет в ленту задачи итог агента. Текст уже redacted; секреты в ленту не попадают."""
        if run.succeeded and run.result is not None:
            text = f"агент завершён: ходов {run.result.num_turns}, итог {run.result.subtype}"
        else:
            text = f"агент: {run.reason or run.state}, код {run.exit_code}"
            if run.stderr_tail:
                text = f"{text}\n{run.stderr_tail}"
        async with self._ctx.session_factory() as session:
            await add_event(
                session, self._task.id, text=truncate_log_text(text), source=TaskEventSource.WORKER
            )


async def _record_failure(
    ctx: DispatchContext, task_id: UUID, reason: str, text: str | None
) -> None:
    """Переводит задачу в error с причиной, если переход разрешён; иначе пишет только событие
    (design 11)."""
    message = reason if text is None else f"{reason}\n{text}"
    message = truncate_log_text(redact(message, extra_values=ctx.secrets))
    async with ctx.session_factory() as session:
        task = await get_task(session, task_id)
        if task.kind is not TaskKind.CHECK and TaskStatus.ERROR in allowed_transitions(
            task.kind, task.status
        ):
            await change_status(
                session, task.id, TaskStatus.ERROR, source=TaskEventSource.WORKER, text=message
            )
        else:
            await add_event(session, task.id, text=message, source=TaskEventSource.WORKER)
    logger.warning("task failed id=%s reason=%s", task_id, reason)


async def _mark_sandbox_error(ctx: DispatchContext, provider_id: str) -> None:
    async with ctx.session_factory() as session:
        row = (
            await session.execute(select(Sandbox).where(Sandbox.provider_id == provider_id))
        ).scalar_one_or_none()
        if row is not None:
            row.status = SandboxStatus.ERROR
            await session.commit()


async def _memory_envs(ctx: DispatchContext, runner: _Runner) -> dict[str, str] | None:
    """env команды memory sync при активации; None — память не настроена (design 4).

    Ключ embeddings из vault попадает в env шага и в redaction runner; без embedding_ref поиск
    памяти лексический, ключа нет.
    """
    memory = ctx.config.sandbox.memory
    if memory is None:
        return None
    embedding = await secret_refs.resolve(ctx.vault, memory.embedding_ref, fallback=None)
    if embedding is None:
        return {}
    runner.secrets = (*runner.secrets, embedding.get_secret_value())
    return {"EMBEDDING_API_KEY": embedding.get_secret_value()}


async def _run_reserved(ctx: DispatchContext, pipeline: Pipeline, reservation: Reservation) -> None:
    """Активация, пайплайн, очистка и пауза для уже закреплённой задачи (design 11–12)."""
    task = reservation.task
    provider_id = reservation.provider_id
    runner = _Runner(ctx, pipeline, provider_id, task)
    readiness_rejected = False
    # Отмена worker (BaseException) пробрасывается без очистки и без отзыва токенов: агент
    # продолжает работать, _recover продолжит задачу, а cleanup отзовёт токены (D-41).
    try:
        marker = f'"$HOME/.harness/projects/{task.workspace_id}.ready"'
        ready = await ctx.provider.exec(provider_id, f"test -f {marker}")
        if ready.exit_code:
            async with ctx.session_factory() as session:
                info = await sandboxes.agent_run_info(session, provider_id)
                live_token = await sandboxes.has_live_task_token(session, task.id)
            artifacts = await ctx.provider.exec(
                provider_id,
                f'test -d "$HOME/.harness/worktrees/{task.id}" -o '
                f'-f "$HOME/.harness/tasks/{task.id}/run.json"',
            )
            readiness_rejected = (
                info.started_at is None and not live_token and artifacts.exit_code != 0
            )
            raise SandboxStepError(
                f"project_not_initialized: выполните agent init {task.workspace_id}"
            )
        # Ключ записи — из vault по repo.access_ref workspace задачи, до активации: без него задача
        # сразу уходит в error, fetch и worktree не выполняются (D-60). Значения сразу попадают в
        # redaction очистки и ответа агента (design 6).
        async with ctx.session_factory() as session:
            workspace = await sandboxes.workspace_for(session, task)
        repo_token = await secret_refs.resolve(ctx.vault, workspace.repo.access_ref, fallback=None)
        if repo_token is None:
            raise SandboxStepError(REPO_ACCESS_REF_REASON.format(workspace_id=workspace.id))
        # Токен, заголовок Basic, его base64 и base64 в URL-кодировке —
        # секреты redaction (D-52, D-62).
        token_value = repo_token.get_secret_value()
        runner.secrets = (
            *runner.secrets,
            token_value,
            *git_access.git_auth_secret_values(workspace.repo.provider, token_value),
        )
        memory_envs = await _memory_envs(ctx, runner)
        await sandboxes.activate(
            ctx.provider,
            provider_id,
            task,
            base_ref=pipeline.base_ref(task, ctx.config),
            timeout_min=ctx.timeout_min,
            repo=workspace.repo,
            repo_token=repo_token,
            default_branch=workspace.default_branch,
            memory_envs=memory_envs,
        )
        outcome: Outcome = await pipeline.run(runner, task)
        if not outcome.ok:
            await _record_failure(
                ctx, task.id, outcome.reason or "пайплайн не завершён", outcome.text
            )
    except (SandboxError, SandboxStepError) as exc:
        await _record_failure(ctx, task.id, exc.reason, None)
    except VaultError:
        # Причину vault не пишем: она может содержать service/name; в ленту — только класс сбоя.
        await _record_failure(ctx, task.id, "vault", None)
    except Exception as exc:
        # Тип исключения, а не его текст: сообщение может содержать вывод команды или ключ.
        await _record_failure(ctx, task.id, f"исключение: {type(exc).__name__}", None)

    # A readiness rejection happens before fetch/worktree/token creation.  Running normal cleanup
    # would turn that operator-actionable error into a sandbox error when the clone does not exist.
    if readiness_rejected:
        try:
            async with ctx.session_factory() as session:
                await sandboxes.release_sandbox(session, ctx.provider, provider_id)
        except Exception as exc:
            logger.error(
                "sandbox release failed provider_id=%s type=%s", provider_id, type(exc).__name__
            )
        return

    try:
        async with ctx.session_factory() as session:
            await sandboxes.cleanup_task(
                session, ctx.provider, provider_id, task, secrets=runner.secrets
            )
    except CleanupFailed:
        logger.error("sandbox left in error after cleanup provider_id=%s", provider_id)
        return
    except Exception as exc:
        await _mark_sandbox_error(ctx, provider_id)
        logger.error(
            "sandbox cleanup error provider_id=%s type=%s", provider_id, type(exc).__name__
        )
        return

    try:
        async with ctx.session_factory() as session:
            await sandboxes.release_sandbox(session, ctx.provider, provider_id)
    except Exception as exc:
        logger.error(
            "sandbox release failed provider_id=%s type=%s", provider_id, type(exc).__name__
        )


async def _recover(ctx: DispatchContext, pipelines: Mapping[TaskKind, Pipeline]) -> bool:
    """Продолжает задачу песочницы, активной до рестарта worker (design 11: восстановление)."""
    async with ctx.session_factory() as session:
        row = (
            await session.execute(
                select(Sandbox).where(
                    Sandbox.current_task_id.is_not(None), Sandbox.status == SandboxStatus.ACTIVE
                )
            )
        ).scalar_one_or_none()
        if row is None or row.current_task_id is None:
            return False
        task = await get_task(session, row.current_task_id)
    pipeline = pipelines.get(task.kind)
    if pipeline is None:
        logger.info("recovery skipped: no pipeline for kind=%s", task.kind)
        return False
    logger.info("recovering task=%s", task.id)
    await _run_reserved(ctx, pipeline, Reservation(provider_id=row.provider_id, task=task))
    return True


async def dispatch_once(
    ctx: DispatchContext, pipelines: Mapping[TaskKind, Pipeline] = PIPELINES
) -> bool:
    """Один шаг диспетчера: восстановление, иначе резервирование задачи из очереди.

    Возвращает True, если песочница была занята задачей на этом шаге. Пустой реестр — False без
    обращения к БД.
    """
    if not pipelines:
        return False
    if await _recover(ctx, pipelines):
        return True
    for pipeline in pipelines.values():
        async with ctx.session_factory() as session:
            reservation = await sandboxes.reserve(session, pipeline)
        if reservation is not None:
            await _run_reserved(ctx, pipeline, reservation)
            return True
    return False


def build_dispatch_context(
    settings: Settings,
    config: HarnessConfig,
    session_factory: async_sessionmaker[AsyncSession],
    provider: SandboxProvider,
) -> DispatchContext | None:
    """Контекст диспетчера из настроек. None, если не заданы ENV агента: названия переменных в лог,
    не значения.

    AGENTS_FLOW_URL = HARNESS_PUBLIC_URL + /mcp (D-38). Пустые ENV считаются отсутствующими.
    """
    missing = [
        name
        for name, value in (
            ("CLAUDE_CODE_OAUTH_TOKEN", settings.claude_code_oauth_token),
            ("HARNESS_PUBLIC_URL", settings.harness_public_url),
        )
        if value is None
    ]
    if missing:
        logger.warning("диспетчер песочницы не запущен: не заданы %s", ", ".join(missing))
        return None
    # Ключи репозиториев — в vault по repo.access_ref; ENV GITLAB_TOKEN не читается (D-60).
    # Проекты без ключа проверяет worker при старте (worker/__init__.py): список берётся из БД.
    assert settings.claude_code_oauth_token is not None
    assert settings.harness_public_url is not None
    return DispatchContext(
        provider=provider,
        config=config,
        session_factory=session_factory,
        oauth_token=settings.claude_code_oauth_token,
        secret_key=settings.harness_secret_key,
        agents_flow_url=f"{settings.harness_public_url.rstrip('/')}/mcp",
        timeout_min=settings.agent_run_timeout_min,
        poll_interval_sec=settings.agent_poll_interval_sec,
        secrets=secret_values(settings),
        vault=build_vault(settings),
    )
