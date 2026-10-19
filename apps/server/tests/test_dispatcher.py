"""Диспетчер песочницы на FakeSandbox и настоящих коммитах Postgres (mvp-06, пункт 4.1).

Пайплайн в тесте регистрируется в реестр dispatch_once; реальные пайплайны появятся в mvp-08/09.
Файлы итога агента пишет сам пайплайн, как сделал бы run.sh; опрос идёт через runner диспетчера.
"""

import asyncio
import base64
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from harness_server.adapters.novita import ExecResult, FakeSandbox
from harness_server.adapters.vault import FakeVault, McpSecretVault, VaultError
from harness_server.config import HarnessConfig, SandboxMemoryConfig, load_config
from harness_server.db.models import Task, TaskToken
from harness_server.db.session import create_engine, create_session_factory
from harness_server.services import sandboxes
from harness_server.services.tasks import create_task, get_task, list_task_events
from harness_server.settings import Settings, load_settings
from harness_server.vault_ref import VaultRef
from harness_server.worker.dispatcher import DispatchContext, build_dispatch_context, dispatch_once
from harness_server.worker.pipeline import AgentRunner, Outcome
from harness_shared.sandboxes import AgentRole, SandboxStatus
from harness_shared.tasks import TaskKind, TaskSource, TaskStatus
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio(loop_scope="session")

Factory = async_sessionmaker[AsyncSession]
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG: HarnessConfig = load_config(REPO_ROOT / "config" / "harness.example.yaml")
PROVIDER_ID = CONFIG.sandbox.provider_id
HOME = "/home/sbx"
SECRET_KEY = "test-secret-key-0123456789abcdef0123"
OAUTH = "oauth-test-value-0123456789abcdef"
GITLAB = "glpat-test-token-0123456789abcdef"
# Движок без подключения: сборка контекста не ходит в БД.
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://u:p@127.0.0.1:1/x"


async def _no_sleep(_seconds: float) -> None:
    return None


def _result_line() -> str:
    event: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 2,
        "session_id": "s-1",
        "usage": {"input_tokens": 1},
    }
    return json.dumps(event)


def _limit_line() -> str:
    """Итог исчерпанного лимита подписки: код 0 и success, но один ход и текст лимита (D-54)."""
    event: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 1,
        "session_id": "s-1",
        "result": "You've hit your session limit · resets 5:30pm (UTC)",
    }
    return json.dumps(event)


AGENT_PID = 4242


class _AgentFake(FakeSandbox):
    """Фейк, у которого группа агента (pid AGENT_PID) живёт по флагу group_alive теста.

    Группа по умолчанию мертва: после запуска агент считается завершившимся. Тест, которому нужен
    живой агент, ставит флаг сам; kill -0 нельзя перерегистрировать в фейке, поэтому флаг читается
    в exec.
    """

    group_alive: bool = False

    async def exec(
        self,
        sandbox_id: str,
        cmd: str,
        *,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float = 60,
    ) -> ExecResult:
        result = await super().exec(sandbox_id, cmd, envs=envs, cwd=cwd, timeout_s=timeout_s)
        if cmd == f"kill -0 -- -{AGENT_PID}" and not self.group_alive:
            return ExecResult(exit_code=1, stdout="", stderr="")
        return result


class _Pipeline:
    """Пайплайн реализации: запускает агента, пишет итог как run.sh, опрашивает через runner."""

    kind = TaskKind.IMPLEMENT
    from_status = TaskStatus.BACKLOG
    to_status: TaskStatus | None = TaskStatus.ACTIVE
    role = AgentRole.IMPLEMENTER

    def __init__(
        self, fake: _AgentFake, *, agent_finishes: bool, stream_line: str | None = None
    ) -> None:
        self._fake = fake
        self._agent_finishes = agent_finishes
        self._stream_line = stream_line

    def base_ref(self, task: Task, config: HarnessConfig) -> str:
        return "main"

    async def run(self, runner: AgentRunner, task: Task) -> Outcome:
        await runner.run_agent("сделай задачу")
        if self._agent_finishes:
            directory = sandboxes.task_dir(HOME, task.id)
            status = {"exit_code": 0, "finished_at": "2026-10-19T10:00:00Z"}
            await self._fake.write_file(PROVIDER_ID, f"{directory}/status.json", json.dumps(status))
            self._fake.respond("tail -n", stdout=self._stream_line or _result_line())
        run = await runner.wait_agent()
        return Outcome(ok=run.succeeded, reason=None if run.succeeded else run.reason)


def _fake(*, home: bool = True) -> _AgentFake:
    fake = _AgentFake(sandbox_id=PROVIDER_ID)
    if home:
        fake.respond('printf %s "$HOME"', stdout=HOME)
    # Команда запуска печатает pid в stdout, как run_agent его ждёт.
    fake.respond("setsid nohup", stdout=f"{AGENT_PID}\n")
    return fake


def _ctx(
    factory: Factory,
    fake: FakeSandbox,
    sleep: Any = _no_sleep,
) -> DispatchContext:
    return DispatchContext(
        provider=fake,
        config=CONFIG,
        session_factory=factory,
        oauth_token=SecretStr(OAUTH),
        gitlab_token=SecretStr(GITLAB),
        secret_key=SecretStr(SECRET_KEY),
        agents_flow_url="https://harness.example/mcp",
        timeout_min=60,
        poll_interval_sec=0.0,
        secrets=(OAUTH, GITLAB),
        sleep=sleep,
    )


async def _seed_agent(
    fake: FakeSandbox,
    task: Task,
    *,
    status_exit: int | None = None,
    stderr: str = "",
    stream: tuple[str, ...] = (),
) -> None:
    """Файлы итога агента, как у run.sh. Время и pid лежат в БД (_set_agent_run)."""
    directory = sandboxes.task_dir(HOME, task.id)
    if status_exit is not None:
        status = {"exit_code": status_exit, "finished_at": "2026-10-19T10:00:00Z"}
        await fake.write_file(PROVIDER_ID, f"{directory}/status.json", json.dumps(status))
    fake.respond("tail -c", stdout=stderr)
    if stream:
        fake.respond("tail -n", stdout="\n".join(stream))


async def _set_agent_run(factory: Factory, *, started_at: datetime | None, pid: int | None) -> None:
    """Серверная запись запуска агента, как её оставил бы запуск до рестарта worker (D-41)."""
    async with factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
        assert row is not None
        row.agent_started_at = started_at
        row.agent_pid = pid
        await session.commit()


async def _backlog_task(factory: Factory) -> Task:
    async with factory() as session:
        return await create_task(
            session,
            kind=TaskKind.IMPLEMENT,
            text="следующая задача",
            source=TaskSource.API,
            known_workspace_ids=["demo"],
            workspace_id="demo",
        )


def _launches(fake: FakeSandbox) -> list[str]:
    return [e.cmd for e in fake.journal if e.cmd is not None and "setsid nohup" in e.cmd]


async def _prepare(factory: Factory) -> Task:
    """Строка песочницы и одна реализация в backlog."""
    async with factory() as session:
        await sandboxes.ensure_sandbox(session, CONFIG)
    async with factory() as session:
        return await create_task(
            session,
            kind=TaskKind.IMPLEMENT,
            text="реализация",
            source=TaskSource.API,
            known_workspace_ids=["demo"],
            workspace_id="demo",
        )


async def _task_status(factory: Factory, task_id: Any) -> TaskStatus:
    async with factory() as session:
        return (await get_task(session, task_id)).status


async def _sandbox_row(factory: Factory) -> tuple[SandboxStatus, Any]:
    async with factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None
    return row.status, row.current_task_id


async def test_empty_registry_does_nothing(committed_session_factory: Factory) -> None:
    fake = _fake()

    busy = await dispatch_once(_ctx(committed_session_factory, fake), {})

    assert busy is False
    assert fake.journal == []


async def test_successful_run_releases_sandbox(committed_session_factory: Factory) -> None:
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipelines = {TaskKind.IMPLEMENT: _Pipeline(fake, agent_finishes=True)}

    busy = await dispatch_once(_ctx(committed_session_factory, fake), pipelines)

    assert busy is True
    assert await _task_status(committed_session_factory, task.id) == TaskStatus.ACTIVE
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)
    assert fake.paused
    assert any(e.cmd and "worktree remove --force" in e.cmd for e in fake.journal)


async def test_usage_limit_result_marks_task_error_without_retry(
    committed_session_factory: Factory,
) -> None:
    """Агент завершился кодом 0, но итог — исчерпанный лимит подписки: задача error с причиной
    usage_limit, текст лимита в ленту не попадает, повторного запуска нет (D-54)."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipelines = {
        TaskKind.IMPLEMENT: _Pipeline(fake, agent_finishes=True, stream_line=_limit_line()),
    }

    await dispatch_once(_ctx(committed_session_factory, fake), pipelines)

    assert await _task_status(committed_session_factory, task.id) == TaskStatus.ERROR
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)
    assert len(_launches(fake)) == 1
    async with committed_session_factory() as session:
        events = await list_task_events(session, task.id)
    texts = [e.text for e in events if e.text]
    assert any("usage_limit" in text for text in texts)
    assert not any("hit your" in text for text in texts)


async def test_lost_agent_marks_task_error_and_releases_sandbox(
    committed_session_factory: Factory,
) -> None:
    """Агент пропал без status.json: задача error с причиной, песочница всё равно освобождается."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipelines = {TaskKind.IMPLEMENT: _Pipeline(fake, agent_finishes=False)}

    await dispatch_once(_ctx(committed_session_factory, fake), pipelines)

    assert await _task_status(committed_session_factory, task.id) == TaskStatus.ERROR
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)
    async with committed_session_factory() as session:
        events = await list_task_events(session, task.id)
    assert any(e.text and "агент завершился без статуса" in e.text for e in events)


async def test_activation_failure_marks_task_and_sandbox_error(
    committed_session_factory: Factory,
) -> None:
    """Нет домашнего каталога: активация падает, очистка тоже, песочница уходит в error."""
    task = await _prepare(committed_session_factory)
    fake = _fake(home=False)
    pipelines = {TaskKind.IMPLEMENT: _Pipeline(fake, agent_finishes=True)}

    await dispatch_once(_ctx(committed_session_factory, fake), pipelines)

    assert await _task_status(committed_session_factory, task.id) == TaskStatus.ERROR
    status, current = await _sandbox_row(committed_session_factory)
    assert status == SandboxStatus.ERROR
    assert current == task.id


async def test_error_sandbox_is_skipped_by_dispatcher(committed_session_factory: Factory) -> None:
    """Песочница в error не берёт новую задачу: dispatch_once возвращает False без запуска."""
    task = await _prepare(committed_session_factory)
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
        assert row is not None
        row.status = SandboxStatus.ERROR
        await session.commit()
    fake = _fake()
    pipelines = {TaskKind.IMPLEMENT: _Pipeline(fake, agent_finishes=True)}

    busy = await dispatch_once(_ctx(committed_session_factory, fake), pipelines)

    assert busy is False
    assert await _task_status(committed_session_factory, task.id) == TaskStatus.BACKLOG
    assert fake.journal == []


async def _reserve_for_pipeline(factory: Factory, pipeline: _Pipeline) -> None:
    """Закрепляет задачу за песочницей, как worker до рестарта (состояние active + current_task)."""
    async with factory() as session:
        reservation = await sandboxes.reserve(session, pipeline)
    assert reservation is not None


async def test_recovery_continues_active_task_without_new_reservation(
    committed_session_factory: Factory,
) -> None:
    """Песочница active с current_task_id: задача продолжается, новая не резервируется, агент
    второй раз не запускается. Живой агент дожидается и даёт итог (design 11, восстановление)."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipeline = _Pipeline(fake, agent_finishes=False)
    await _reserve_for_pipeline(committed_session_factory, pipeline)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=AGENT_PID)
    await _seed_agent(fake, task)
    fake.group_alive = True
    queued = await _backlog_task(committed_session_factory)
    directory = sandboxes.task_dir(HOME, task.id)

    async def finish_on_first_poll(_seconds: float) -> None:
        fake.group_alive = False
        status = {"exit_code": 0, "finished_at": "2026-10-19T10:00:00Z"}
        await fake.write_file(PROVIDER_ID, f"{directory}/status.json", json.dumps(status))
        fake.respond("tail -n", stdout=_result_line())

    busy = await dispatch_once(
        _ctx(committed_session_factory, fake, sleep=finish_on_first_poll),
        {TaskKind.IMPLEMENT: pipeline},
    )

    assert busy is True
    assert _launches(fake) == []
    assert await _task_status(committed_session_factory, task.id) == TaskStatus.ACTIVE
    assert await _task_status(committed_session_factory, queued.id) == TaskStatus.BACKLOG
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)


async def test_recovery_with_dead_agent_marks_task_error(
    committed_session_factory: Factory,
) -> None:
    """Запуск записан на сервере, процесс мёртв, status.json нет: DIED, без повторного запуска."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipeline = _Pipeline(fake, agent_finishes=False)
    await _reserve_for_pipeline(committed_session_factory, pipeline)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=AGENT_PID)
    await _seed_agent(fake, task)

    await dispatch_once(_ctx(committed_session_factory, fake), {TaskKind.IMPLEMENT: pipeline})

    assert _launches(fake) == []
    assert await _task_status(committed_session_factory, task.id) == TaskStatus.ERROR
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)
    async with committed_session_factory() as session:
        events = await list_task_events(session, task.id)
    assert any(e.text and "агент завершился без статуса" in e.text for e in events)


async def test_agent_output_secret_stays_out_of_events(
    committed_session_factory: Factory,
) -> None:
    """Токен в хвосте потока и в stderr не попадает в ленту задачи (design 14)."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipeline = _Pipeline(fake, agent_finishes=False)
    await _reserve_for_pipeline(committed_session_factory, pipeline)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=AGENT_PID)
    result = {
        "type": "result",
        "subtype": "error_max_turns",
        "is_error": True,
        "num_turns": 5,
        "session_id": OAUTH,
    }
    await _seed_agent(
        fake,
        task,
        status_exit=1,
        stderr=f"ошибка с токеном {OAUTH}",
        stream=(json.dumps({"type": "assistant", "text": OAUTH}), json.dumps(result)),
    )

    await dispatch_once(_ctx(committed_session_factory, fake), {TaskKind.IMPLEMENT: pipeline})

    async with committed_session_factory() as session:
        events = await list_task_events(session, task.id)
    assert events
    assert all(e.text is None or OAUTH not in e.text for e in events)
    assert any(e.text and "агент" in e.text for e in events)


async def test_activation_failure_before_worktree_returns_sandbox_to_paused(
    committed_session_factory: Factory,
) -> None:
    """Сбой git fetch до worktree: задача в error, очистка проходит (worktree и ветки нет),
    песочница паузится без ручной правки БД, и resume проходит."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    fake.respond("git -C /home/sbx/work/demo fetch", exit_code=1, stderr="fatal: network")
    pipelines = {TaskKind.IMPLEMENT: _Pipeline(fake, agent_finishes=True)}

    await dispatch_once(_ctx(committed_session_factory, fake), pipelines)

    assert await _task_status(committed_session_factory, task.id) == TaskStatus.ERROR
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)
    assert fake.paused
    assert any(e.cmd and "worktree remove --force" in e.cmd for e in fake.journal)
    journal_before_resume = len(fake.journal)
    async with committed_session_factory() as session:
        await sandboxes.resume_sandbox(session, fake, PROVIDER_ID)
    # Песочница уже на паузе: resume — пустая операция, провайдер не вызывается (design 8).
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)
    assert fake.paused
    assert len(fake.journal) == journal_before_resume


class _CancelledPipeline(_Pipeline):
    """Пайплайн, у которого отменяют worker сразу после запуска агента."""

    async def run(self, runner: AgentRunner, task: Task) -> Outcome:
        await runner.run_agent("сделай задачу")
        raise asyncio.CancelledError


async def test_cancelled_pipeline_keeps_task_tokens(
    committed_session_factory: Factory,
) -> None:
    """Отмена worker во время пайплайна: токены задачи не отзываются, песочница остаётся занятой
    задачей и записью запуска, чтобы восстановление продолжило её (D-41)."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipelines = {TaskKind.IMPLEMENT: _CancelledPipeline(fake, agent_finishes=False)}

    with pytest.raises(asyncio.CancelledError):
        await dispatch_once(_ctx(committed_session_factory, fake), pipelines)

    async with committed_session_factory() as session:
        stored = (
            (await session.execute(select(TaskToken).where(TaskToken.task_id == task.id)))
            .scalars()
            .all()
        )
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert stored and all(token.revoked_at is None for token in stored)
    assert row is not None
    assert row.status == SandboxStatus.ACTIVE
    assert row.current_task_id == task.id
    assert row.agent_started_at is not None


async def test_recovery_after_cancel_revokes_tokens_on_cleanup(
    committed_session_factory: Factory,
) -> None:
    """После отмены worker задача продолжается без нового запуска, токены отзываются в cleanup."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    cancelled = {TaskKind.IMPLEMENT: _CancelledPipeline(fake, agent_finishes=False)}
    with pytest.raises(asyncio.CancelledError):
        await dispatch_once(_ctx(committed_session_factory, fake), cancelled)

    busy = await dispatch_once(
        _ctx(committed_session_factory, fake),
        {TaskKind.IMPLEMENT: _Pipeline(fake, agent_finishes=True)},
    )

    assert busy is True
    assert len(_launches(fake)) == 1
    async with committed_session_factory() as session:
        stored = (
            (await session.execute(select(TaskToken).where(TaskToken.task_id == task.id)))
            .scalars()
            .all()
        )
    assert stored and all(token.revoked_at is not None for token in stored)
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)
    assert fake.paused


# --- sandbox-profile: ключи из vault и память в диспетчере (design 6) ---

VAULT_GITLAB = "glpat-vault-value-0123456789abcdef"
VAULT_EMBEDDING = "emb-vault-value-0123456789abcdef"
GITLAB_REF = "vault:demo/gitlab/main"
EMBEDDING_REF = "vault:demo/polza/embeddings"
# Фиктивный sha для тестов (D-51): настоящий закреплённый коммит — только в harness.yaml и D-51.
MEMORY_REF = "0123456789abcdef0123456789abcdef01234567"


def _vault_config(*, memory: bool) -> HarnessConfig:
    """Конфиг с ссылками на vault; memory — блок памяти с ключом embeddings из vault."""
    gitlab = CONFIG.gitlab.model_copy(update={"access_ref": GITLAB_REF})
    sandbox_update: dict[str, Any] = {}
    if memory:
        sandbox_update["memory"] = SandboxMemoryConfig(ref=MEMORY_REF, embedding_ref=EMBEDDING_REF)
    sandbox = CONFIG.sandbox.model_copy(update=sandbox_update)
    return CONFIG.model_copy(update={"gitlab": gitlab, "sandbox": sandbox})


async def test_gitlab_key_comes_from_vault_and_env_is_not_needed(
    committed_session_factory: Factory,
) -> None:
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipeline = _Pipeline(fake, agent_finishes=True)
    vault = FakeVault({VaultRef("demo", "gitlab", "main"): VAULT_GITLAB})
    ctx = replace(
        _ctx(committed_session_factory, fake),
        config=_vault_config(memory=False),
        gitlab_token=None,
        vault=vault,
    )

    await dispatch_once(ctx, {TaskKind.IMPLEMENT: pipeline})

    assert vault.requested == [VaultRef("demo", "gitlab", "main")]
    # Ключ из vault уходит git только заголовком на префикс base_url (D-52), не как GITLAB_TOKEN.
    assert fake.received_env("GITLAB_TOKEN") is None
    assert fake.received_env("GIT_CONFIG_KEY_0") == "http.https://gitlab.com/.extraHeader"
    header = fake.received_env("GIT_CONFIG_VALUE_0") or ""
    decoded = base64.b64decode(header.split()[-1]).decode()
    assert decoded == f"oauth2:{VAULT_GITLAB}"
    assert await _task_status(committed_session_factory, task.id) == TaskStatus.ACTIVE
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)


async def test_vault_failure_marks_task_error_and_cleans_up(
    committed_session_factory: Factory,
) -> None:
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipeline = _Pipeline(fake, agent_finishes=True)
    vault = FakeVault(fail=VaultError("unavailable", ref="gitlab/main"))
    ctx = replace(
        _ctx(committed_session_factory, fake), config=_vault_config(memory=False), vault=vault
    )

    await dispatch_once(ctx, {TaskKind.IMPLEMENT: pipeline})

    assert await _task_status(committed_session_factory, task.id) == TaskStatus.ERROR
    assert await _sandbox_row(committed_session_factory) == (SandboxStatus.PAUSED, None)
    assert not [e for e in fake.journal if e.cmd and "worktree add" in e.cmd]
    async with committed_session_factory() as session:
        events = await list_task_events(session, task.id)
    assert any(e.text and "vault" in e.text for e in events)
    assert all(e.text is None or "gitlab/main" not in e.text for e in events)


async def test_memory_embedding_key_goes_to_sync_env_and_is_redacted(
    committed_session_factory: Factory,
) -> None:
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipeline = _Pipeline(fake, agent_finishes=False)
    await _reserve_for_pipeline(committed_session_factory, pipeline)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=AGENT_PID)
    vault = FakeVault(
        {
            VaultRef("demo", "gitlab", "main"): VAULT_GITLAB,
            VaultRef("demo", "polza", "embeddings"): VAULT_EMBEDDING,
        }
    )
    await _seed_agent(fake, task, status_exit=1, stderr=f"эхо ключа {VAULT_EMBEDDING}")
    ctx = replace(
        _ctx(committed_session_factory, fake),
        config=_vault_config(memory=True),
        vault=vault,
    )

    await dispatch_once(ctx, {TaskKind.IMPLEMENT: pipeline})

    sync = [e for e in fake.journal if e.cmd and "memory sync" in e.cmd]
    assert sync and sync[0].env_keys == ("EMBEDDING_API_KEY",)
    async with committed_session_factory() as session:
        events = await list_task_events(session, task.id)
    assert all(e.text is None or VAULT_EMBEDDING not in e.text for e in events)
    assert all(e.text is None or VAULT_GITLAB not in e.text for e in events)


# --- sandbox-profile: сборка контекста диспетчера (tasks 2.3, пункт 5 ревью) ---


def _dispatch_settings(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, *, gitlab_env: bool
) -> Settings:
    """Settings для build_dispatch_context: ENV агента заданы, GITLAB_TOKEN — по флагу."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", OAUTH)
    monkeypatch.setenv("HARNESS_PUBLIC_URL", "https://harness.example.com")
    if gitlab_env:
        monkeypatch.setenv("GITLAB_TOKEN", GITLAB)
    else:
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    return load_settings()


async def test_build_context_takes_vault_and_no_gitlab_env_when_access_ref_set(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_MCP_URL", "https://vault.example/mcp")
    monkeypatch.setenv("VAULT_MCP_TOKEN", "vault-token-test-0123456789abcdef")
    settings = _dispatch_settings(valid_env, monkeypatch, gitlab_env=False)
    factory = create_session_factory(create_engine(UNREACHABLE_DATABASE_URL))

    ctx = build_dispatch_context(
        settings, _vault_config(memory=False), factory, FakeSandbox(sandbox_id=PROVIDER_ID)
    )

    assert ctx is not None
    assert isinstance(ctx.vault, McpSecretVault)
    assert ctx.gitlab_token is None


async def test_build_context_without_access_ref_or_token_returns_none(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _dispatch_settings(valid_env, monkeypatch, gitlab_env=False)
    factory = create_session_factory(create_engine(UNREACHABLE_DATABASE_URL))

    ctx = build_dispatch_context(settings, CONFIG, factory, FakeSandbox(sandbox_id=PROVIDER_ID))

    assert ctx is None
    assert "GITLAB_TOKEN" in caplog.text
    assert "vault" not in caplog.text.lower()


async def test_build_context_without_access_ref_uses_env_token(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _dispatch_settings(valid_env, monkeypatch, gitlab_env=True)
    factory = create_session_factory(create_engine(UNREACHABLE_DATABASE_URL))

    ctx = build_dispatch_context(settings, CONFIG, factory, FakeSandbox(sandbox_id=PROVIDER_ID))

    assert ctx is not None
    assert ctx.vault is None
    assert ctx.gitlab_token is not None
    assert ctx.gitlab_token.get_secret_value() == GITLAB


async def test_dispatcher_fetch_is_bound_to_gitlab_base_url(
    committed_session_factory: Factory,
) -> None:
    """Диспетчер передаёт базовый адрес GitLab в fetch: заголовок только на его префикс (D-52)."""
    await _prepare(committed_session_factory)
    fake = _fake()
    pipelines = {TaskKind.IMPLEMENT: _Pipeline(fake, agent_finishes=True)}

    await dispatch_once(_ctx(committed_session_factory, fake), pipelines)

    assert fake.received_env("GIT_CONFIG_KEY_0") == "http.https://gitlab.com/.extraHeader"
    assert fake.received_env("GIT_ASKPASS") is None


async def test_auth_header_value_is_redacted_from_agent_output(
    committed_session_factory: Factory,
) -> None:
    """Base64 заголовка Basic от токена GitLab — секрет: в ленте задачи его быть не должно."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipeline = _Pipeline(fake, agent_finishes=False)
    await _reserve_for_pipeline(committed_session_factory, pipeline)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=AGENT_PID)
    header = sandboxes.git_auth_header(VAULT_GITLAB)
    encoded = header.removeprefix("Authorization: Basic ")
    vault = FakeVault({VaultRef("demo", "gitlab", "main"): VAULT_GITLAB})
    await _seed_agent(fake, task, status_exit=1, stderr=f"эхо заголовка {header}")
    ctx = replace(
        _ctx(committed_session_factory, fake), config=_vault_config(memory=False), vault=vault
    )

    await dispatch_once(ctx, {TaskKind.IMPLEMENT: pipeline})

    async with committed_session_factory() as session:
        events = await list_task_events(session, task.id)
    assert all(e.text is None or encoded not in e.text for e in events)
    assert all(e.text is None or VAULT_GITLAB not in e.text for e in events)


async def test_bare_base64_auth_value_is_redacted_from_agent_output(
    committed_session_factory: Factory,
) -> None:
    """Голый base64 из заголовка (без префикса Authorization) тоже редактируется (D-52, ревью)."""
    task = await _prepare(committed_session_factory)
    fake = _fake()
    pipeline = _Pipeline(fake, agent_finishes=False)
    await _reserve_for_pipeline(committed_session_factory, pipeline)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=AGENT_PID)
    _, bare = sandboxes.git_auth_secret_values(VAULT_GITLAB)
    vault = FakeVault({VaultRef("demo", "gitlab", "main"): VAULT_GITLAB})
    await _seed_agent(fake, task, status_exit=1, stderr=f"base64 без префикса: {bare}")
    ctx = replace(
        _ctx(committed_session_factory, fake), config=_vault_config(memory=False), vault=vault
    )

    await dispatch_once(ctx, {TaskKind.IMPLEMENT: pipeline})

    async with committed_session_factory() as session:
        events = await list_task_events(session, task.id)
    assert all(e.text is None or bare not in e.text for e in events)
    assert any(e.text and "[REDACTED]" in e.text for e in events)


async def test_dispatcher_launch_env_carries_default_git_author(
    committed_session_factory: Factory,
) -> None:
    """Агент запускается с автором коммитов из sandbox.git_author (по умолчанию agents-flow)."""
    await _prepare(committed_session_factory)
    fake = _fake()
    pipelines = {TaskKind.IMPLEMENT: _Pipeline(fake, agent_finishes=True)}

    await dispatch_once(_ctx(committed_session_factory, fake), pipelines)

    assert fake.received_env("GIT_AUTHOR_NAME") == "agents-flow"
    assert fake.received_env("GIT_COMMITTER_EMAIL") == "agents-flow@noreply.local"
