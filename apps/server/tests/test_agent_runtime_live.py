"""Живая проверка рантайма агента (mvp-06, пункт 6.12): сервисный путь на настоящей песочнице.

Запуск (владелец, вручную): LIVE_NOVITA_API_KEY=… LIVE_NOVITA_SANDBOX_ID=… \
LIVE_CLAUDE_CODE_OAUTH_TOKEN=… uv run pytest -m live apps/server/tests/test_agent_runtime_live.py
Нужны Postgres (TEST_DATABASE_URL или testcontainers) и песочница, подготовленная bootstrap.sh
(claude в PATH). Без переменных тесты пропускаются. Значения ключей не печатаются.

Тест сам создаёт в песочнице локальный репозиторий workspace (~/work/<id>) с bare origin в /tmp:
activate выполняет git fetch origin и worktree add, GitLab для этого не нужен. Всё созданное
удаляется в finally. Агент получает недостижимый адрес MCP, поэтому данные задачи наружу не уходят.
"""

import asyncio
import os
import secrets
import shlex
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from harness_server.adapters.novita import (
    ExecResult,
    NovitaSandboxProvider,
    SandboxProvider,
)
from harness_server.config import HarnessConfig, load_config
from harness_server.db.models import Task, TaskToken
from harness_server.services import sandboxes
from harness_server.services.agent_result import AgentRun, AgentState
from harness_server.services.sandboxes import AgentStartState
from harness_server.services.tasks import create_task
from harness_shared.tasks import TaskKind, TaskSource, TaskStatus
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]

Factory = async_sessionmaker[AsyncSession]
REPO_ROOT = Path(__file__).resolve().parents[3]
# Из примера берутся только лимиты и структура; provider_id подменяется id настоящей песочницы.
BASE_CONFIG: HarnessConfig = load_config(REPO_ROOT / "config" / "harness.example.yaml")

# default_branch тестового workspace: base_ref для activate (design 10).
DEFAULT_BRANCH = "main"
# Таймаут агента для wait_agent и срока токена; короткий, чтобы зависший агент не держал тест долго.
AGENT_TIMEOUT_MIN = 15
# Лимит ходов: короткая задача завершается за пару ходов, второй сценарий убивается раньше.
SHORT_MAX_TURNS = 5
LONG_MAX_TURNS = 30
SHORT_PROMPT = 'создай файл hello.py с print("hello world") и закончи'
LONG_PROMPT = (
    "Выполни по шагам: создай файлы part01.txt … part40.txt, в каждом напиши его номер; "
    "затем прочитай все файлы и выведи сумму номеров."
)
# Недостижимый адрес: агент не должен достучаться до боевого сервера из тестовой песочницы.
UNREACHABLE_MCP_URL = "http://127.0.0.1:9/mcp"
# Значение для GITLAB_TOKEN в activate: origin локальный, токен не используется.
UNUSED_GITLAB_TOKEN = "local-origin-unused"
SHORT_TIMEOUT_SEC = 60
GIT_TIMEOUT_SEC = 300
POLL_SEC = 5
WAIT_LIMIT_SEC = 900
STREAM_WAIT_SEC = 180
STOP_WAIT_SEC = 10


class _ImplementStage:
    """Пайплайн для резервирования: реализация из backlog в active (как mvp-09 будет делать)."""

    kind = TaskKind.IMPLEMENT
    from_status = TaskStatus.BACKLOG
    to_status: TaskStatus | None = TaskStatus.ACTIVE


def _live_settings() -> tuple[str, str, str, str | None]:
    """Читает переменные live-теста; без обязательных — пропуск, не падение."""
    api_key = os.environ.get("LIVE_NOVITA_API_KEY")
    sandbox_id = os.environ.get("LIVE_NOVITA_SANDBOX_ID")
    oauth_token = os.environ.get("LIVE_CLAUDE_CODE_OAUTH_TOKEN")
    if not api_key or not sandbox_id or not oauth_token:
        pytest.skip(
            "нужны LIVE_NOVITA_API_KEY, LIVE_NOVITA_SANDBOX_ID, LIVE_CLAUDE_CODE_OAUTH_TOKEN"
        )
    return api_key, sandbox_id, oauth_token, os.environ.get("LIVE_NOVITA_DOMAIN")


@pytest.fixture
def provider() -> SandboxProvider:
    api_key, _, _, domain = _live_settings()
    return NovitaSandboxProvider(api_key=api_key, domain=domain)


@pytest.fixture
def sandbox_id() -> str:
    _, sandbox, _, _ = _live_settings()
    return sandbox


@pytest.fixture
def oauth_token() -> str:
    _, _, token, _ = _live_settings()
    return token


@pytest.fixture
def live_config(sandbox_id: str) -> HarnessConfig:
    """Конфиг с provider_id настоящей песочницы: строка в БД должна ссылаться на неё."""
    sandbox = BASE_CONFIG.sandbox.model_copy(update={"provider_id": sandbox_id})
    return BASE_CONFIG.model_copy(update={"sandbox": sandbox})


@pytest.fixture
async def factory(committed_session_factory: Factory) -> AsyncIterator[Factory]:
    """Имя фабрики для тестов: настоящие коммиты; очистка таблиц — в committed_session_factory."""
    yield committed_session_factory


async def _must(provider: SandboxProvider, sandbox_id: str, cmd: str, what: str) -> ExecResult:
    """exec, после которого ненулевой код — провал теста с понятной причиной."""
    result = await provider.exec(sandbox_id, cmd, timeout_s=SHORT_TIMEOUT_SEC)
    assert result.exit_code == 0, f"{what}: код {result.exit_code}, stderr: {result.stderr[-500:]}"
    return result


async def _exists(provider: SandboxProvider, sandbox_id: str, path: str) -> bool:
    result = await provider.exec(sandbox_id, f"test -e {shlex.quote(path)}", timeout_s=60)
    return result.exit_code == 0


async def _home(provider: SandboxProvider, sandbox_id: str) -> str:
    result = await _must(provider, sandbox_id, 'printf %s "$HOME"', "HOME")
    home = result.stdout.strip()
    assert home.startswith("/"), "HOME песочницы не абсолютный путь"
    return home


async def _create_repo(
    provider: SandboxProvider, sandbox_id: str, home: str, workspace: str
) -> tuple[str, str]:
    """Локальный репозиторий workspace: ~/work/<id> с одним коммитом на main и bare origin в /tmp.

    Возвращает (корень тестового каталога, путь репозитория). Чужой каталог не трогается: путь
    содержит случайный id, и его существование проверяется до создания.
    """
    root = f"/tmp/harness-live-{uuid.uuid4().hex}"
    origin = f"{root}/origin.git"
    repo = f"{home}/work/{workspace}"
    assert not await _exists(provider, sandbox_id, repo), "каталог workspace уже существует"
    await _must(
        provider,
        sandbox_id,
        f"mkdir -p {shlex.quote(root)} {shlex.quote(home + '/work')}",
        "mkdir",
    )
    await _must(provider, sandbox_id, f"git init -q --bare {shlex.quote(origin)}", "init origin")
    await _must(
        provider,
        sandbox_id,
        f"git init -q {shlex.quote(repo)} && "
        f"git -C {shlex.quote(repo)} symbolic-ref HEAD refs/heads/{DEFAULT_BRANCH}",
        "init repo",
    )
    await provider.write_file(sandbox_id, f"{repo}/README.md", "live repo\n")
    git = f"git -C {shlex.quote(repo)}"
    await _must(
        provider,
        sandbox_id,
        f"{git} add README.md && {git} -c user.name=live "
        "-c user.email=live@example.invalid commit -q -m init",
        "commit",
    )
    await _must(
        provider,
        sandbox_id,
        f"{git} remote add origin {shlex.quote(origin)} && {git} push -q origin {DEFAULT_BRANCH}",
        "push origin",
    )
    return root, repo


async def _ensure_mcp_config(provider: SandboxProvider, sandbox_id: str, home: str) -> bool:
    """run.sh передаёт --mcp-config ~/.harness/mcp.json, его создаёт bootstrap. Если файла нет,
    тест создаёт пустой и возвращает True: тогда тест же его и удаляет."""
    path = f"{home}/.harness/mcp.json"
    if await _exists(provider, sandbox_id, path):
        return False
    await _must(provider, sandbox_id, f"mkdir -p {shlex.quote(home + '/.harness')}", "mkdir")
    await provider.write_file(sandbox_id, path, '{"mcpServers": {}}\n')
    return True


async def _teardown(
    provider: SandboxProvider,
    sandbox_id: str,
    *,
    home: str,
    root: str,
    repo: str,
    task: Task,
    pid: int | None,
    mcp_created: bool,
) -> None:
    """Всё, что тест создал в песочнице. Вызывается в finally, в том числе после сбоя шага.

    Живую группу агента убиваем первой: иначе она пишет в каталог, который удаляем.
    """
    if pid is not None and await sandboxes._is_alive(provider, sandbox_id, pid):
        await provider.exec(sandbox_id, f"kill -KILL -- -{pid}", timeout_s=SHORT_TIMEOUT_SEC)
    paths = [
        root,
        repo,
        sandboxes.task_dir(home, task.id),
        sandboxes.worktree_dir(home, task.id),
    ]
    if mcp_created:
        paths.append(f"{home}/.harness/mcp.json")
    await provider.exec(
        sandbox_id,
        "rm -rf " + " ".join(shlex.quote(path) for path in paths),
        timeout_s=GIT_TIMEOUT_SEC,
    )


async def _ensure(factory: Factory, config: HarnessConfig) -> None:
    async with factory() as session:
        await sandboxes.ensure_sandbox(session, config)


async def _reserve_task(factory: Factory, workspace: str, text: str) -> Task:
    """Задача в backlog и её резервирование песочницы, как делает worker (design 9)."""
    async with factory() as session:
        task = await create_task(
            session,
            kind=TaskKind.IMPLEMENT,
            text=text,
            source=TaskSource.API,
            known_workspace_ids=[workspace],
            workspace_id=workspace,
        )
    async with factory() as session:
        reservation = await sandboxes.reserve(session, _ImplementStage())
    assert reservation is not None and reservation.task.id == task.id
    return task


async def _activate(provider: SandboxProvider, sandbox_id: str, task: Task) -> None:
    await sandboxes.activate(
        provider,
        sandbox_id,
        task,
        base_ref=DEFAULT_BRANCH,
        timeout_min=AGENT_TIMEOUT_MIN,
        gitlab_token=SecretStr(UNUSED_GITLAB_TOKEN),
    )


async def _run(
    factory: Factory,
    provider: SandboxProvider,
    sandbox_id: str,
    task: Task,
    *,
    prompt: str,
    max_turns: int,
    secret_key: str,
    oauth_token: str,
) -> sandboxes.AgentStart:
    async with factory() as session:
        return await sandboxes.run_agent(
            session,
            provider,
            sandbox_id,
            task,
            prompt=prompt,
            max_turns=max_turns,
            timeout_min=AGENT_TIMEOUT_MIN,
            secret_key=SecretStr(secret_key),
            oauth_token=SecretStr(oauth_token),
            agents_flow_url=UNREACHABLE_MCP_URL,
        )


async def _agent_info(factory: Factory, sandbox_id: str) -> sandboxes.AgentRunInfo:
    async with factory() as session:
        return await sandboxes.agent_run_info(session, sandbox_id)


async def _wait_once(
    provider: SandboxProvider,
    sandbox_id: str,
    factory: Factory,
    task: Task,
    secret_values: tuple[str, ...],
) -> AgentRun:
    """Один опрос как в worker: время и pid берутся из БД, а не из файлов песочницы (D-41)."""
    info = await _agent_info(factory, sandbox_id)
    return await sandboxes.wait_agent(
        provider,
        sandbox_id,
        task,
        started_at=info.started_at,
        pid=info.pid,
        timeout_min=AGENT_TIMEOUT_MIN,
        now=datetime.now(UTC),
        secrets=secret_values,
    )


async def _wait_finished(
    provider: SandboxProvider,
    sandbox_id: str,
    factory: Factory,
    task: Task,
    secret_values: tuple[str, ...],
) -> AgentRun:
    """Опрос до итога с интервалом POLL_SEC и предельным временем WAIT_LIMIT_SEC."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_LIMIT_SEC
    while True:
        run = await _wait_once(provider, sandbox_id, factory, task, secret_values)
        if run.state is not AgentState.RUNNING:
            return run
        if loop.time() > deadline:
            pytest.fail("агент не завершился за отведённое время")
        await asyncio.sleep(POLL_SEC)


async def _wait_stream_started(provider: SandboxProvider, sandbox_id: str, directory: str) -> None:
    """Агент начал писать поток: только тогда его можно убивать «в работе», а не до старта."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + STREAM_WAIT_SEC
    while loop.time() < deadline:
        stream = await provider.read_file(sandbox_id, f"{directory}/stream.jsonl")
        if stream:
            return
        await asyncio.sleep(2)
    pytest.fail("агент не начал писать stream.jsonl")


async def _wait_group_gone(provider: SandboxProvider, sandbox_id: str, pid: int) -> None:
    for _ in range(STOP_WAIT_SEC):
        if not await sandboxes._is_alive(provider, sandbox_id, pid):
            return
        await asyncio.sleep(1)
    pytest.fail("группа агента жива после SIGKILL")


async def _token_rows(factory: Factory, task_id: uuid.UUID) -> list[TaskToken]:
    async with factory() as session:
        result = await session.execute(select(TaskToken).where(TaskToken.task_id == task_id))
        return list(result.scalars().all())


async def test_live_success_path_activate_run_wait_cleanup(
    provider: SandboxProvider,
    sandbox_id: str,
    oauth_token: str,
    live_config: HarnessConfig,
    factory: Factory,
) -> None:
    workspace = f"live-{uuid.uuid4().hex[:8]}"
    home = await _home(provider, sandbox_id)
    await _ensure(factory, live_config)
    task = await _reserve_task(factory, workspace, SHORT_PROMPT)
    root, repo = await _create_repo(provider, sandbox_id, home, workspace)
    mcp_created = await _ensure_mcp_config(provider, sandbox_id, home)
    directory = sandboxes.task_dir(home, task.id)
    worktree = sandboxes.worktree_dir(home, task.id)
    secret_key = secrets.token_urlsafe(32)
    pid: int | None = None
    try:
        await _activate(provider, sandbox_id, task)
        start = await _run(
            factory,
            provider,
            sandbox_id,
            task,
            prompt=SHORT_PROMPT,
            max_turns=SHORT_MAX_TURNS,
            secret_key=secret_key,
            oauth_token=oauth_token,
        )
        assert start.state is AgentStartState.STARTED
        assert start.token is not None
        token = start.token.get_secret_value()
        secret_values = (oauth_token, token)

        info = await _agent_info(factory, sandbox_id)
        assert info.started_at is not None
        assert info.pid is not None and info.pid > 1
        pid = info.pid

        # Prompt идёт через stdin; в run.sh и файлах нет ни текста задачи, ни кредов.
        prompt_path = f"{directory}/prompt.md"
        assert await provider.read_file(sandbox_id, prompt_path) == SHORT_PROMPT
        run_sh = await provider.read_file(sandbox_id, f"{directory}/run.sh")
        assert run_sh is not None
        assert f"< {shlex.quote(prompt_path)} >" in run_sh
        assert SHORT_PROMPT not in run_sh
        assert oauth_token not in run_sh and token not in run_sh

        # Группа агента видна сразу после запуска: агент работает, итог ещё не принят.
        assert await sandboxes._is_alive(provider, sandbox_id, pid), (
            "группа агента не видна сразу после запуска"
        )

        run = await _wait_finished(provider, sandbox_id, factory, task, secret_values)
        assert run.state is AgentState.FINISHED, run.reason
        assert run.succeeded
        assert run.result is not None
        hello = await provider.read_file(sandbox_id, f"{worktree}/hello.py")
        assert hello is not None and "hello world" in hello

        async with factory() as session:
            await sandboxes.cleanup_task(session, provider, sandbox_id, task, secrets=secret_values)

        rows = await _token_rows(factory, task.id)
        assert rows and all(row.revoked_at is not None for row in rows)
        assert not await _exists(provider, sandbox_id, worktree)
        assert not await _exists(provider, sandbox_id, directory)
        branch = f"refs/heads/task/{task.id}"
        show_ref = await provider.exec(
            sandbox_id,
            f"git -C {shlex.quote(repo)} show-ref --verify --quiet {shlex.quote(branch)}",
            timeout_s=SHORT_TIMEOUT_SEC,
        )
        assert show_ref.exit_code != 0, "ветка task/<id> осталась после очистки"
    finally:
        await _teardown(
            provider,
            sandbox_id,
            home=home,
            root=root,
            repo=repo,
            task=task,
            pid=pid,
            mcp_created=mcp_created,
        )


async def test_live_killed_agent_is_died_without_relaunch(
    provider: SandboxProvider,
    sandbox_id: str,
    oauth_token: str,
    live_config: HarnessConfig,
    factory: Factory,
) -> None:
    workspace = f"live-{uuid.uuid4().hex[:8]}"
    home = await _home(provider, sandbox_id)
    await _ensure(factory, live_config)
    task = await _reserve_task(factory, workspace, LONG_PROMPT)
    root, repo = await _create_repo(provider, sandbox_id, home, workspace)
    mcp_created = await _ensure_mcp_config(provider, sandbox_id, home)
    directory = sandboxes.task_dir(home, task.id)
    worktree = sandboxes.worktree_dir(home, task.id)
    secret_key = secrets.token_urlsafe(32)
    pid: int | None = None
    try:
        await _activate(provider, sandbox_id, task)
        start = await _run(
            factory,
            provider,
            sandbox_id,
            task,
            prompt=LONG_PROMPT,
            max_turns=LONG_MAX_TURNS,
            secret_key=secret_key,
            oauth_token=oauth_token,
        )
        assert start.state is AgentStartState.STARTED
        assert start.token is not None
        token = start.token.get_secret_value()
        secret_values = (oauth_token, token)

        info = await _agent_info(factory, sandbox_id)
        assert info.started_at is not None and info.pid is not None and info.pid > 1
        pid = info.pid
        started_at = info.started_at

        # Агент работает (поток пошёл), затем убиваем всю группу, как при падении песочницы.
        await _wait_stream_started(provider, sandbox_id, directory)
        kill = await provider.exec(sandbox_id, f"kill -KILL -- -{pid}", timeout_s=60)
        assert kill.exit_code == 0, "группа агента не найдена до убийства: агент уже завершился"
        await _wait_group_gone(provider, sandbox_id, pid)

        # Итога без статуса быть не должно; если status.json успел появиться, удаляем его.
        await provider.exec(
            sandbox_id, f"rm -f {shlex.quote(f'{directory}/status.json')}", timeout_s=60
        )
        assert await provider.read_file(sandbox_id, f"{directory}/status.json") is None

        run = await _wait_once(provider, sandbox_id, factory, task, secret_values)
        assert run.state is AgentState.DIED
        assert run.reason == "агент завершился без статуса"

        # Повторный запуск не стартует агента: серверная запись остаётся, процесса нет (design 10).
        second = await _run(
            factory,
            provider,
            sandbox_id,
            task,
            prompt=LONG_PROMPT,
            max_turns=LONG_MAX_TURNS,
            secret_key=secret_key,
            oauth_token=oauth_token,
        )
        assert second.state is AgentStartState.DIED
        assert second.token is None
        after = await _agent_info(factory, sandbox_id)
        assert after.pid == pid and after.started_at == started_at

        async with factory() as session:
            await sandboxes.cleanup_task(session, provider, sandbox_id, task, secrets=secret_values)

        rows = await _token_rows(factory, task.id)
        assert rows and all(row.revoked_at is not None for row in rows)
        assert not await _exists(provider, sandbox_id, worktree)
        assert not await _exists(provider, sandbox_id, directory)
    finally:
        await _teardown(
            provider,
            sandbox_id,
            home=home,
            root=root,
            repo=repo,
            task=task,
            pid=pid,
            mcp_created=mcp_created,
        )
