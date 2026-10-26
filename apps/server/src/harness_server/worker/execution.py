"""Активация, пайплайн и очистка. Отмена сохраняет процесс для восстановления (D-41)."""

import asyncio
import logging
from contextlib import suppress
from uuid import uuid4

from harness_shared.planning import PlanFinishIn
from harness_shared.tasks import TaskKind, TaskStatus
from harness_shared.worker import ClaimOut
from harness_shared.worker_reports import EventIn, StatusIn

from harness_server.adapters.sandbox import SandboxError
from harness_server.adapters.vault import VaultError
from harness_server.adapters.worker_api import WorkerAPIError
from harness_server.security.redaction import redact
from harness_server.services import git_access, sandboxes
from harness_server.services import secrets as secret_refs
from harness_server.services.agent_result import truncate_log_text
from harness_server.services.sandboxes import CleanupFailed, SandboxStepError
from harness_server.worker.context import DispatchContext
from harness_server.worker.pipeline import Pipeline
from harness_server.worker.runner import Runner
from harness_server.worker.runner import heartbeat as send_heartbeats

logger = logging.getLogger(__name__)
REPO_ACCESS_REF_REASON = (
    "repo_access_ref: у workspace {workspace_id} нет repo.access_ref — "
    "задаче нужен ключ записи (push)"
)


async def _failure(runner: Runner, reason: str, text: str | None = None) -> None:
    message = reason if text is None else f"{reason}\n{text}"
    message = truncate_log_text(redact(message, extra_values=runner.secrets))
    body = StatusIn(external_key=str(uuid4()), text=message, status=TaskStatus.ERROR)
    try:
        if runner.claim.task.kind == TaskKind.PLAN:
            await runner.ctx.client.plan_finish(
                runner.claim.task.id,
                PlanFinishIn(external_key=body.external_key, status="error", text=message),
                runner.claim.task_token,
            )
        else:
            await runner.ctx.client.report(
                runner.claim.task.id, "status", body, runner.claim.task_token
            )
    except WorkerAPIError as exc:
        if exc.status_code != 409:
            raise
        await runner.ctx.client.report(
            runner.claim.task.id,
            "events",
            EventIn(external_key=body.external_key, text=message),
            runner.claim.task_token,
        )
    logger.warning("task failed id=%s reason=%s", runner.claim.task.id, reason)


async def run_reserved(
    ctx: DispatchContext,
    pipeline: Pipeline,
    claim: ClaimOut,
    provider_id: str,
    *,
    cleanup: bool = False,
) -> None:
    """Сетевые операции короткие; запуск, git, опрос и очистка выполняются на машине worker."""
    task = claim.task
    runner = Runner(ctx, claim, provider_id)
    heartbeat = None if cleanup else asyncio.create_task(send_heartbeats(ctx, claim))
    readiness_rejected = False
    try:
        if not cleanup:
            marker = f'"$HOME/.harness/projects/{task.workspace_id}.ready"'
            ready = await ctx.provider.exec(provider_id, f"test -f {marker}")
            if ready.exit_code:
                info = await runner.store.info()
                artifacts = await ctx.provider.exec(
                    provider_id,
                    f'test -d "$HOME/.harness/worktrees/{task.id}" -o '
                    f'-f "$HOME/.harness/tasks/{task.id}/run.json"',
                )
                readiness_rejected = info.started_at is None and artifacts.exit_code != 0
                raise SandboxStepError(
                    f"project_not_initialized: выполните agent init {task.workspace_id}"
                )
            workspace = claim.project
            repo_token = await secret_refs.resolve(
                ctx.vault, workspace.repo.access_ref, fallback=None
            )
            if repo_token is None:
                raise SandboxStepError(REPO_ACCESS_REF_REASON.format(workspace_id=workspace.id))
            value = repo_token.get_secret_value()
            runner.repo_token = repo_token
            runner.secrets = (
                *runner.secrets,
                value,
                *git_access.git_auth_secret_values(workspace.repo.provider, value),
            )
            memory_envs = None
            if ctx.config.sandbox.memory is not None:
                embedding = await secret_refs.resolve(
                    ctx.vault, ctx.config.sandbox.memory.embedding_ref, fallback=None
                )
                memory_envs = {}
                if embedding is not None:
                    runner.secrets = (*runner.secrets, embedding.get_secret_value())
                    memory_envs["EMBEDDING_API_KEY"] = embedding.get_secret_value()
            await sandboxes.activate(
                ctx.provider,
                provider_id,
                task,
                base_ref=pipeline.base_ref(task, workspace),
                timeout_min=ctx.timeout_min,
                repo=workspace.repo,
                repo_token=repo_token,
                default_branch=workspace.default_branch,
                memory_envs=memory_envs,
            )
            outcome = await pipeline.run(runner, task)
            if not outcome.ok:
                await _failure(runner, outcome.reason or "пайплайн не завершён", outcome.text)
    except (SandboxError, SandboxStepError) as exc:
        await _failure(runner, exc.reason)
    except VaultError:
        await _failure(runner, "vault")
    except WorkerAPIError:
        raise
    except Exception as exc:
        await _failure(runner, f"исключение: {type(exc).__name__}")
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
    try:
        if readiness_rejected:
            await runner.store.revoke_tokens(task.id)
        else:
            await sandboxes.cleanup_task(
                runner.store, ctx.provider, provider_id, task, secrets=runner.secrets
            )
        await ctx.provider.pause(provider_id)
        await runner.store.release()
    except CleanupFailed:
        logger.error("sandbox left in error after cleanup provider_id=%s", provider_id)
    except WorkerAPIError:
        raise
    except Exception as exc:
        await runner.store.mark_error()
        logger.error(
            "sandbox cleanup failed provider_id=%s type=%s", provider_id, type(exc).__name__
        )
