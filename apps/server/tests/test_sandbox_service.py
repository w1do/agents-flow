"""Сервис песочниц на FakeSandbox и настоящих коммитах Postgres (mvp-06, пункты 3.3–3.7).

Фейк не запускает агента: файлы итога (status.json, stream.jsonl, pid) тест пишет сам, как сделал бы
run.sh в песочнице. Проверяется резервирование, активация, запуск, опрос итога, очистка и пауза.
"""

import asyncio
import json
import shlex
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from harness_server.adapters.novita import FakeSandbox
from harness_server.config import HarnessConfig, load_config
from harness_server.db.models import Task, TaskToken
from harness_server.security import tokens
from harness_server.services import sandboxes
from harness_server.services.agent_result import AgentRun, AgentState, parse_pid
from harness_server.services.sandboxes import (
    AgentStartState,
    CleanupFailed,
    SandboxBusy,
)
from harness_server.services.tasks import create_task, get_task
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
REPO = f"{HOME}/work/demo"
SECRET_KEY = "test-secret-key-0123456789abcdef0123"
# Значения тестовые, в формате настоящих секретов, но не настоящие.
OAUTH = "oauth-test-value-0123456789abcdef"
GITLAB = "glpat-test-token-0123456789abcdef"


class _Stage:
    """Пайплайн для резервирования: реализация из backlog в active (как mvp-09 будет делать)."""

    kind = TaskKind.IMPLEMENT
    from_status = TaskStatus.BACKLOG
    to_status: TaskStatus | None = TaskStatus.ACTIVE
    role = AgentRole.IMPLEMENTER


def _fake(
    *, home: bool = True, branch: str | None = None, launch_stdout: str | None = "4242\n"
) -> FakeSandbox:
    """Фейк песочницы; branch — ветка текущего worktree, None — worktree ещё нет.

    launch_stdout — вывод команды запуска агента (pid, как печатает run_agent); None — без ответа.
    """
    fake = FakeSandbox(sandbox_id=PROVIDER_ID)
    if home:
        fake.respond('printf %s "$HOME"', stdout=HOME)
    if branch is not None:
        fake.respond("git -C", stdout=branch)
    if launch_stdout is not None:
        fake.respond("setsid nohup", stdout=launch_stdout)
    return fake


def _orphan_task(workspace: str | None = "demo") -> Task:
    """Задача без БД: для функций, которые читают только id и workspace_id."""
    return Task(id=uuid.uuid4(), workspace_id=workspace)


async def _ensure(factory: Factory) -> None:
    async with factory() as session:
        await sandboxes.ensure_sandbox(session, CONFIG)


async def _task(factory: Factory) -> Task:
    async with factory() as session:
        return await create_task(
            session,
            kind=TaskKind.IMPLEMENT,
            text="реализация",
            source=TaskSource.API,
            known_workspace_ids=["demo"],
            workspace_id="demo",
        )


async def _set_sandbox_status(factory: Factory, status: SandboxStatus) -> None:
    async with factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
        assert row is not None
        row.status = status
        await session.commit()


async def _start(
    factory: Factory, fake: FakeSandbox, task: Task, *, now: datetime | None = None
) -> sandboxes.AgentStart:
    # run_agent читает строку песочницы из БД, поэтому она должна существовать.
    await _ensure(factory)
    async with factory() as session:
        return await sandboxes.run_agent(
            session,
            fake,
            PROVIDER_ID,
            task,
            prompt="сделай задачу",
            max_turns=50,
            timeout_min=60,
            secret_key=SecretStr(SECRET_KEY),
            oauth_token=SecretStr(OAUTH),
            agents_flow_url="https://harness.example/mcp",
            now=now,
        )


async def _set_agent_run(factory: Factory, *, started_at: datetime | None, pid: int | None) -> None:
    """Серверная запись запуска агента (колонки sandboxes), как её оставил бы прежний запуск."""
    async with factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
        assert row is not None
        row.agent_started_at = started_at
        row.agent_pid = pid
        await session.commit()


async def _seed_run(
    fake: FakeSandbox,
    task: Task,
    *,
    status_exit: int | None = None,
    stream: tuple[str, ...] = (),
    stderr: str = "",
) -> str:
    """Файлы итога агента, которые создал бы run.sh. Время и pid здесь не пишутся: они в БД.

    Возвращает каталог задачи.
    """
    directory = sandboxes.task_dir(HOME, task.id)
    if status_exit is not None:
        status = {"exit_code": status_exit, "finished_at": "2026-10-19T10:00:00Z"}
        await fake.write_file(PROVIDER_ID, f"{directory}/status.json", json.dumps(status))
    # stderr читается командой tail -c, а не файлом целиком: отвечаем как tail на хвост файла.
    fake.respond("tail -c", stdout=stderr[-8000:])
    if stream:
        fake.respond("tail -n", stdout="\n".join(stream))
    return directory


def _result_line(num_turns: int = 3, session_id: str = "s-1") -> str:
    event: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": num_turns,
        "session_id": session_id,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return json.dumps(event)


def _launches(fake: FakeSandbox) -> list[str]:
    return [e.cmd for e in fake.journal if e.cmd is not None and "setsid nohup" in e.cmd]


# --- 3.3 Строка песочницы и резервирование ---


async def test_ensure_sandbox_creates_paused_row_once(committed_session_factory: Factory) -> None:
    async with committed_session_factory() as session:
        first = await sandboxes.ensure_sandbox(session, CONFIG)
        second = await sandboxes.ensure_sandbox(session, CONFIG)

    assert first.id == second.id
    assert first.status == SandboxStatus.PAUSED
    assert first.agent_type == "claude-code"


async def test_ensure_sandbox_keeps_existing_status(committed_session_factory: Factory) -> None:
    await _ensure(committed_session_factory)
    await _set_sandbox_status(committed_session_factory, SandboxStatus.ACTIVE)

    await _ensure(committed_session_factory)

    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None and row.status == SandboxStatus.ACTIVE


async def test_reserve_takes_free_sandbox_and_task(committed_session_factory: Factory) -> None:
    await _ensure(committed_session_factory)
    task = await _task(committed_session_factory)

    async with committed_session_factory() as session:
        reservation = await sandboxes.reserve(session, _Stage())

    assert reservation is not None
    assert reservation.task.id == task.id
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None
    assert row.current_task_id == task.id
    assert row.status == SandboxStatus.ACTIVE


async def test_busy_sandbox_leaves_second_task_queued(committed_session_factory: Factory) -> None:
    """Песочница занята: задача B остаётся в прежнем статусе (сценарий «Песочница занята»)."""
    await _ensure(committed_session_factory)
    first = await _task(committed_session_factory)
    second = await _task(committed_session_factory)

    async with committed_session_factory() as session:
        taken = await sandboxes.reserve(session, _Stage())
    async with committed_session_factory() as session:
        blocked = await sandboxes.reserve(session, _Stage())

    assert taken is not None and taken.task.id == first.id
    assert blocked is None
    async with committed_session_factory() as session:
        task_b = await get_task(session, second.id)
    assert task_b.status == TaskStatus.BACKLOG


async def test_error_sandbox_is_not_taken(committed_session_factory: Factory) -> None:
    """Песочница в error задачи не берёт, пока оператор не сделает resume (design 8)."""
    await _ensure(committed_session_factory)
    task = await _task(committed_session_factory)
    await _set_sandbox_status(committed_session_factory, SandboxStatus.ERROR)

    async with committed_session_factory() as session:
        reservation = await sandboxes.reserve(session, _Stage())

    assert reservation is None
    async with committed_session_factory() as session:
        task_row = await get_task(session, task.id)
    assert task_row.status == TaskStatus.BACKLOG


async def test_parallel_reserve_takes_one_sandbox(committed_session_factory: Factory) -> None:
    await _ensure(committed_session_factory)
    await _task(committed_session_factory)
    await _task(committed_session_factory)

    async def take() -> sandboxes.Reservation | None:
        async with committed_session_factory() as session:
            return await sandboxes.reserve(session, _Stage())

    results = await asyncio.gather(take(), take())

    assert sum(result is not None for result in results) == 1


# --- 3.4 Активация ---


async def test_activate_extends_timeout_and_creates_worktree() -> None:
    task = _orphan_task()
    fake = _fake()

    await sandboxes.activate(
        fake,
        PROVIDER_ID,
        task,
        base_ref="main",
        timeout_min=60,
        gitlab_token=SecretStr(GITLAB),
    )

    assert fake.timeout_s == 70 * 60
    adds = [e for e in fake.journal if e.cmd and "worktree add -B" in e.cmd]
    assert len(adds) == 1
    assert f"task/{task.id}" in (adds[0].cmd or "")
    assert all(GITLAB not in (e.cmd or "") for e in fake.journal)


async def test_repeated_activation_skips_worktree_add() -> None:
    """Повторная активация: worktree уже на ветке task/<id>, worktree add не пишется в журнал."""
    task = _orphan_task()
    fake = _fake(branch=f"task/{task.id}")

    await sandboxes.activate(
        fake,
        PROVIDER_ID,
        task,
        base_ref="main",
        timeout_min=60,
        gitlab_token=SecretStr(GITLAB),
    )

    assert not [e for e in fake.journal if e.cmd and "worktree add" in e.cmd]


async def test_activate_refuses_foreign_worktree_branch() -> None:
    task = _orphan_task()
    fake = _fake(branch="feature/other")

    with pytest.raises(sandboxes.SandboxStepError) as info:
        await sandboxes.activate(
            fake,
            PROVIDER_ID,
            task,
            base_ref="main",
            timeout_min=60,
            gitlab_token=SecretStr(GITLAB),
        )

    assert info.value.reason == "worktree_branch"
    assert not [e for e in fake.journal if e.cmd and "worktree add" in e.cmd]


# --- 3.5 Запуск агента ---


async def test_run_agent_keeps_credentials_off_disk_and_out_of_other_commands(
    committed_session_factory: Factory,
) -> None:
    task = await _task(committed_session_factory)
    fake = _fake()

    start = await _start(committed_session_factory, fake, task)

    assert start.state is AgentStartState.STARTED
    assert start.token is not None
    token = start.token.get_secret_value()
    assert fake.received_env("CLAUDE_CODE_OAUTH_TOKEN") == OAUTH
    assert fake.received_env("AGENTS_FLOW_TOKEN") == token
    for needle in (OAUTH, token):
        assert fake.files_containing(needle) == []
    launches = [e for e in fake.journal if e.cmd and "setsid nohup" in e.cmd]
    assert len(launches) == 1
    assert launches[0].env_keys == (
        "AGENTS_FLOW_TOKEN",
        "AGENTS_FLOW_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
    )
    # Ни одна команда не получает ключ API: подписка задаётся только CLAUDE_CODE_OAUTH_TOKEN (D-18).
    assert all("ANTHROPIC_API_KEY" not in e.env_keys for e in fake.journal)
    assert all("ANTHROPIC_AUTH_TOKEN" not in e.env_keys for e in fake.journal)


async def test_run_agent_writes_isolation_flags_and_stores_only_hash(
    committed_session_factory: Factory,
) -> None:
    task = await _task(committed_session_factory)
    fake = _fake()

    start = await _start(committed_session_factory, fake, task)

    assert start.token is not None
    directory = sandboxes.task_dir(HOME, task.id)
    run_sh = await fake.read_file(PROVIDER_ID, f"{directory}/run.sh")
    assert run_sh is not None
    assert "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN" in run_sh
    assert "--setting-sources user" in run_sh
    assert "--strict-mcp-config" in run_sh
    assert "--max-turns 50" in run_sh
    async with committed_session_factory() as session:
        stored = (
            (await session.execute(select(TaskToken).where(TaskToken.task_id == task.id)))
            .scalars()
            .all()
        )
    assert [row.token_hash for row in stored] == [
        tokens.hash_token(start.token.get_secret_value(), SECRET_KEY)
    ]


async def test_second_run_does_not_launch_again(committed_session_factory: Factory) -> None:
    task = await _task(committed_session_factory)
    fake = _fake()
    await _start(committed_session_factory, fake, task)

    second = await _start(committed_session_factory, fake, task)

    assert second.state is AgentStartState.ALREADY_RUNNING
    assert second.token is None
    assert len(_launches(fake)) == 1


async def test_run_agent_after_finish_reports_already_finished(
    committed_session_factory: Factory,
) -> None:
    task = await _task(committed_session_factory)
    fake = _fake()
    await _start(committed_session_factory, fake, task)
    directory = sandboxes.task_dir(HOME, task.id)
    await fake.write_file(PROVIDER_ID, f"{directory}/status.json", '{"exit_code": 0}')
    # Группа агента уже мертва: иначе запуск считается «ещё идёт» (ALREADY_RUNNING).
    fake.respond("kill -0 -- -4242", exit_code=1)

    second = await _start(committed_session_factory, fake, task)

    assert second.state is AgentStartState.ALREADY_FINISHED
    assert len(_launches(fake)) == 1


async def test_run_agent_with_dead_pid_reports_died_without_launch(
    committed_session_factory: Factory,
) -> None:
    """Запуск записан на сервере, процесса нет, status.json нет: агент умер без итога. Не «уже идёт»
    и не повторный запуск (design 10)."""
    task = await _task(committed_session_factory)
    fake = _fake()
    await _ensure(committed_session_factory)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=4242)
    fake.respond("kill -0 -- -4242", exit_code=1)

    start = await _start(committed_session_factory, fake, task)

    assert start.state is AgentStartState.DIED
    assert start.token is None
    assert _launches(fake) == []


async def test_run_agent_passes_prompt_via_stdin_not_argv(
    committed_session_factory: Factory,
) -> None:
    """Текст задачи, начинающийся с «--», не попадает в argv claude: prompt идёт через stdin."""
    task = await _task(committed_session_factory)
    fake = _fake()
    await _ensure(committed_session_factory)
    prompt = "--dangerously-skip-permissions сделай задачу"
    directory = sandboxes.task_dir(HOME, task.id)

    async with committed_session_factory() as session:
        await sandboxes.run_agent(
            session,
            fake,
            PROVIDER_ID,
            task,
            prompt=prompt,
            max_turns=50,
            timeout_min=60,
            secret_key=SecretStr(SECRET_KEY),
            oauth_token=SecretStr(OAUTH),
            agents_flow_url="https://harness.example/mcp",
        )

    assert await fake.read_file(PROVIDER_ID, f"{directory}/prompt.md") == prompt
    run_sh = await fake.read_file(PROVIDER_ID, f"{directory}/run.sh")
    assert run_sh is not None
    assert f"< {shlex.quote(f'{directory}/prompt.md')} >" in run_sh
    assert "$(cat" not in run_sh
    assert prompt not in run_sh


async def test_run_agent_records_started_at_and_pid(committed_session_factory: Factory) -> None:
    task = await _task(committed_session_factory)
    fake = _fake()
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

    await _start(committed_session_factory, fake, task, now=now)

    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None
    assert row.agent_started_at == now
    assert row.agent_pid == 4242
    run_text = await fake.read_file(PROVIDER_ID, f"{sandboxes.task_dir(HOME, task.id)}/run.json")
    assert run_text is not None
    run_info = json.loads(run_text)
    assert run_info["role"] == "implementer"
    assert run_info["task_id"] == str(task.id)


async def test_run_agent_invalid_launch_pid_raises(committed_session_factory: Factory) -> None:
    task = await _task(committed_session_factory)
    fake = _fake(launch_stdout="")

    with pytest.raises(sandboxes.SandboxStepError) as info:
        await _start(committed_session_factory, fake, task)

    assert info.value.reason == "launch_pid"
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None and row.agent_started_at is not None


async def test_run_agent_recovers_pid_from_file(committed_session_factory: Factory) -> None:
    """Упал между запуском и записью agent_pid: pid берём из файла, повторного запуска нет."""
    task = await _task(committed_session_factory)
    fake = _fake()
    await _ensure(committed_session_factory)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=None)
    await fake.write_file(PROVIDER_ID, f"{sandboxes.task_dir(HOME, task.id)}/pid", "4242")

    start = await _start(committed_session_factory, fake, task)

    assert start.state is AgentStartState.ALREADY_RUNNING
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None and row.agent_pid == 4242
    assert _launches(fake) == []


async def test_run_agent_pid_one_in_file_is_died(committed_session_factory: Factory) -> None:
    """Файл pid со значением 1 не принимается: агент мёртв, kill -0 -- -1 не выполняется."""
    task = await _task(committed_session_factory)
    fake = _fake()
    await _ensure(committed_session_factory)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=None)
    await fake.write_file(PROVIDER_ID, f"{sandboxes.task_dir(HOME, task.id)}/pid", "1")

    start = await _start(committed_session_factory, fake, task)

    assert start.state is AgentStartState.DIED
    assert not [e for e in fake.journal if e.cmd and "kill -0" in e.cmd]
    assert _launches(fake) == []


async def test_run_agent_files_without_db_record_not_relaunched(
    committed_session_factory: Factory,
) -> None:
    """Файлы есть, серверной записи нет: файлам не доверяем, агента повторно не запускаем."""
    task = await _task(committed_session_factory)
    fake = _fake()
    await fake.write_file(PROVIDER_ID, f"{sandboxes.task_dir(HOME, task.id)}/pid", "4242")

    start = await _start(committed_session_factory, fake, task)

    assert start.state is AgentStartState.DIED
    assert start.token is None
    assert _launches(fake) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", None),
        ("1", None),
        ("-5", None),
        ("abc", None),
        ("", None),
        ("2", 2),
        (" 4242\n", 4242),
        ("²", None),
        ("99999999999", None),
        ("4194305", None),
        ("4194304", 4194304),
    ],
)
async def test_parse_pid_accepts_only_ascii_linux_range(text: str, expected: int | None) -> None:
    assert parse_pid(text) == expected


async def test_is_alive_skips_exec_for_pid_one() -> None:
    fake = _fake()

    assert await sandboxes._is_alive(fake, PROVIDER_ID, 1) is False
    assert not [e for e in fake.journal if e.cmd and "kill -0" in e.cmd]


# --- 3.6 Опрос итога ---


async def _wait(
    fake: FakeSandbox,
    task: Task,
    *,
    started_at: datetime | None,
    pid: int | None = 4242,
    timeout_min: int = 60,
    now: datetime | None = None,
    secrets: tuple[str, ...] = (),
) -> AgentRun:
    return await sandboxes.wait_agent(
        fake,
        PROVIDER_ID,
        task,
        started_at=started_at,
        pid=pid,
        timeout_min=timeout_min,
        now=now if now is not None else datetime.now(UTC),
        secrets=secrets,
    )


async def test_wait_agent_reports_finished_success() -> None:
    task = _orphan_task()
    fake = _fake()
    fake.respond("kill -0 -- -4242", exit_code=1)
    await _seed_run(fake, task, status_exit=0, stream=(_result_line(num_turns=3),))

    run = await _wait(fake, task, started_at=datetime.now(UTC), secrets=(OAUTH,))

    assert run.state is AgentState.FINISHED
    assert run.succeeded
    assert run.result is not None and run.result.num_turns == 3


async def test_wait_agent_reports_running_while_process_alive() -> None:
    task = _orphan_task()
    fake = _fake()
    await _seed_run(fake, task)

    run = await _wait(fake, task, started_at=datetime.now(UTC))

    assert run.state is AgentState.RUNNING


async def test_wait_agent_status_with_alive_group_is_running() -> None:
    """status.json записан, но группа жива: агент работает, итог не принимается (D-41)."""
    task = _orphan_task()
    fake = _fake()
    await _seed_run(fake, task, status_exit=0)

    run = await _wait(fake, task, started_at=datetime.now(UTC))

    assert run.state is AgentState.RUNNING


async def test_wait_agent_times_out_and_kills_group() -> None:
    task = _orphan_task()
    fake = _fake()
    now = datetime.now(UTC)
    await _seed_run(fake, task)

    run = await _wait(fake, task, started_at=now - timedelta(minutes=61), now=now)

    assert run.state is AgentState.TIMED_OUT
    assert run.reason == "превышено время"
    assert any(e.cmd and "kill -TERM -- -4242" in e.cmd for e in fake.journal)


async def test_wait_agent_ignores_forged_run_json() -> None:
    """run.json подменён на будущее время: таймаут считается от серверного started_at (D-41)."""
    task = _orphan_task()
    fake = _fake()
    now = datetime.now(UTC)
    forged = {
        "started_at": (now + timedelta(days=1)).isoformat(),
        "max_turns": 50,
        "task_id": str(task.id),
    }
    directory = sandboxes.task_dir(HOME, task.id)
    await fake.write_file(PROVIDER_ID, f"{directory}/run.json", json.dumps(forged))
    await _seed_run(fake, task)

    run = await _wait(fake, task, started_at=now - timedelta(minutes=61), now=now)

    assert run.state is AgentState.TIMED_OUT
    assert any(e.cmd and "kill -TERM -- -4242" in e.cmd for e in fake.journal)


async def test_wait_agent_uses_server_pid_not_file() -> None:
    """pid из файла (999) не используется: проверяется и убивается только серверный pid."""
    task = _orphan_task()
    fake = _fake()
    directory = sandboxes.task_dir(HOME, task.id)
    await fake.write_file(PROVIDER_ID, f"{directory}/pid", "999")
    fake.respond("kill -0 -- -4242", exit_code=1)
    await _seed_run(fake, task, status_exit=0)

    run = await _wait(fake, task, started_at=datetime.now(UTC), pid=4242)

    assert run.state is AgentState.FINISHED
    assert not [e for e in fake.journal if e.cmd and "-999" in e.cmd]


async def test_wait_agent_without_started_at_does_not_exec() -> None:
    """Агент не запускался (нет записи на сервере): DIED без единого вызова песочницы."""
    task = _orphan_task()
    fake = _fake()

    run = await _wait(fake, task, started_at=None, pid=None)

    assert run.state is AgentState.DIED
    assert fake.journal == []


async def test_wait_agent_reports_agent_lost_without_status() -> None:
    task = _orphan_task()
    fake = _fake()
    fake.respond("kill -0 -- -4242", exit_code=1)
    await _seed_run(fake, task)

    run = await _wait(fake, task, started_at=datetime.now(UTC))

    assert run.state is AgentState.DIED
    assert run.reason == "агент завершился без статуса"


async def test_wait_agent_redacts_secret_in_agent_output() -> None:
    task = _orphan_task()
    fake = _fake()
    fake.respond("kill -0 -- -4242", exit_code=1)
    await _seed_run(
        fake,
        task,
        status_exit=1,
        stderr=f"ошибка с токеном {OAUTH}",
        # Токен в хвосте потока: в событии assistant и в итоге result (session_id).
        stream=(
            f'{{"type": "assistant", "text": "{OAUTH}"}}',
            _result_line(session_id=OAUTH),
        ),
    )

    run = await _wait(fake, task, started_at=datetime.now(UTC), secrets=(OAUTH,))

    assert run.state is AgentState.FINISHED
    assert run.exit_code == 1
    assert OAUTH not in run.stderr_tail
    assert "ошибка с токеном" in run.stderr_tail
    assert run.result is not None
    assert OAUTH not in repr(run.result)
    assert run.result.session_id is not None and OAUTH not in run.result.session_id


async def test_wait_agent_reads_only_stderr_tail() -> None:
    """Большой stderr не читается файлом целиком: только хвост командой tail -c (пункт J)."""
    task = _orphan_task()
    fake = _fake()
    fake.respond("kill -0 -- -4242", exit_code=1)
    stderr = "a" * 50_000 + "конец"
    await _seed_run(fake, task, status_exit=1, stderr=stderr)

    run = await _wait(fake, task, started_at=datetime.now(UTC))

    assert run.stderr_tail.endswith("конец")
    assert len(run.stderr_tail) <= 2000
    stderr_path = f"{sandboxes.task_dir(HOME, task.id)}/stderr.log"
    assert not [e for e in fake.journal if e.method == "read_file" and e.cmd == stderr_path]
    assert [e for e in fake.journal if e.cmd and e.cmd.startswith("tail -c")]


# --- 3.7 Очистка и пауза ---


async def test_successful_cleanup_revokes_tokens_and_pauses(
    committed_session_factory: Factory,
) -> None:
    await _ensure(committed_session_factory)
    task = await _task(committed_session_factory)
    async with committed_session_factory() as session:
        reservation = await sandboxes.reserve(session, _Stage())
    assert reservation is not None
    async with committed_session_factory() as session:
        await sandboxes.issue_task_token(
            session, task.id, secret_key=SECRET_KEY, agent_run_timeout_min=60
        )
    fake = _fake()

    async with committed_session_factory() as session:
        await sandboxes.cleanup_task(session, fake, PROVIDER_ID, task, secrets=(GITLAB,))
    async with committed_session_factory() as session:
        await sandboxes.release_sandbox(session, fake, PROVIDER_ID)

    assert fake.paused
    assert any(e.cmd and "worktree remove --force" in e.cmd for e in fake.journal)
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
        stored = (
            (await session.execute(select(TaskToken).where(TaskToken.task_id == task.id)))
            .scalars()
            .all()
        )
    assert row is not None
    assert row.current_task_id is None
    assert row.status == SandboxStatus.PAUSED
    assert stored and all(token.revoked_at is not None for token in stored)


@pytest.mark.parametrize(
    ("agent_pid", "group_alive"),
    [(4242, True), (4242, False), (None, False)],
    ids=["pid_alive", "pid_dead", "no_pid"],
)
async def test_cleanup_kills_agent_group_only_when_recorded_and_alive(
    committed_session_factory: Factory, agent_pid: int | None, group_alive: bool
) -> None:
    """Живая группа агента убивается до удаления каталога. Мёртвая группа и отсутствующий pid —
    без kill: очистка не ждёт KILL_GRACE_SEC впустую."""
    await _ensure(committed_session_factory)
    task = await _task(committed_session_factory)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=agent_pid)
    fake = _fake()
    if agent_pid is not None and not group_alive:
        fake.respond("kill -0 -- -4242", exit_code=1)

    async with committed_session_factory() as session:
        await sandboxes.cleanup_task(session, fake, PROVIDER_ID, task, secrets=())

    probes = [e for e in fake.journal if e.cmd and "kill -0" in e.cmd]
    kills = [i for i, e in enumerate(fake.journal) if e.cmd and "kill -TERM -- -4242" in e.cmd]
    removals = [i for i, e in enumerate(fake.journal) if e.cmd and e.cmd.startswith("rm -rf")]
    assert bool(probes) == (agent_pid is not None)
    assert bool(kills) == (agent_pid is not None and group_alive)
    assert removals
    if kills:
        assert kills[0] < removals[0]


async def test_failed_cleanup_puts_sandbox_in_error(committed_session_factory: Factory) -> None:
    await _ensure(committed_session_factory)
    task = await _task(committed_session_factory)
    async with committed_session_factory() as session:
        reservation = await sandboxes.reserve(session, _Stage())
    assert reservation is not None
    async with committed_session_factory() as session:
        await sandboxes.issue_task_token(
            session, task.id, secret_key=SECRET_KEY, agent_run_timeout_min=60
        )
    fake = _fake()
    fake.respond(f"git -C {REPO} worktree remove", exit_code=1, stderr="fatal")

    with pytest.raises(CleanupFailed):
        async with committed_session_factory() as session:
            await sandboxes.cleanup_task(session, fake, PROVIDER_ID, task, secrets=())

    assert not fake.paused
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
        stored = (
            (await session.execute(select(TaskToken).where(TaskToken.task_id == task.id)))
            .scalars()
            .all()
        )
    assert row is not None
    assert row.status == SandboxStatus.ERROR
    assert row.current_task_id == task.id
    # Отзыв не зависит от исхода очистки: токен задачи отозван даже при сбое (пункт B).
    assert stored and all(token.revoked_at is not None for token in stored)


async def test_manual_pause_refuses_busy_sandbox(committed_session_factory: Factory) -> None:
    await _ensure(committed_session_factory)
    await _task(committed_session_factory)
    async with committed_session_factory() as session:
        await sandboxes.reserve(session, _Stage())
    fake = _fake()

    with pytest.raises(SandboxBusy):
        async with committed_session_factory() as session:
            await sandboxes.pause_sandbox(session, fake, PROVIDER_ID)

    assert not fake.paused


async def test_cleanup_without_workspace_removes_task_dir(
    committed_session_factory: Factory,
) -> None:
    """Задача без workspace (активация упала на no_workspace): git не вызывается, каталог задачи
    удаляется, токены отозваны (design 12)."""
    await _ensure(committed_session_factory)
    task = await _task(committed_session_factory)
    async with committed_session_factory() as session:
        db_task = await get_task(session, task.id)
        db_task.workspace_id = None
        await session.commit()
        await sandboxes.issue_task_token(
            session, task.id, secret_key=SECRET_KEY, agent_run_timeout_min=60
        )
    task.workspace_id = None
    fake = _fake()

    async with committed_session_factory() as session:
        await sandboxes.cleanup_task(session, fake, PROVIDER_ID, task, secrets=())

    assert not [e for e in fake.journal if e.cmd and "git -C" in e.cmd]
    assert [
        e for e in fake.journal if e.cmd and e.cmd.startswith("rm -rf") and str(task.id) in e.cmd
    ]
    async with committed_session_factory() as session:
        stored = (
            (await session.execute(select(TaskToken).where(TaskToken.task_id == task.id)))
            .scalars()
            .all()
        )
    assert stored and all(token.revoked_at is not None for token in stored)


async def test_reserve_and_release_reset_agent_columns(
    committed_session_factory: Factory,
) -> None:
    """Остатки прежнего запуска в колонках агента сбрасываются при резервировании и освобождении."""
    await _ensure(committed_session_factory)
    await _task(committed_session_factory)
    stale = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    await _set_agent_run(committed_session_factory, started_at=stale, pid=4242)
    async with committed_session_factory() as session:
        reservation = await sandboxes.reserve(session, _Stage())
    assert reservation is not None
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None
    assert row.agent_started_at is None and row.agent_pid is None

    await _set_agent_run(committed_session_factory, started_at=stale, pid=4242)
    fake = _fake()
    async with committed_session_factory() as session:
        await sandboxes.release_sandbox(session, fake, PROVIDER_ID)
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None
    assert row.agent_started_at is None and row.agent_pid is None
    assert row.current_task_id is None and row.status == SandboxStatus.PAUSED


async def test_resume_error_connects_pauses_and_frees(committed_session_factory: Factory) -> None:
    await _ensure(committed_session_factory)
    await _set_sandbox_status(committed_session_factory, SandboxStatus.ERROR)
    await _set_agent_run(committed_session_factory, started_at=datetime.now(UTC), pid=4242)
    fake = FakeSandbox(sandbox_id=PROVIDER_ID, paused=True)

    async with committed_session_factory() as session:
        await sandboxes.resume_sandbox(session, fake, PROVIDER_ID)

    assert [e.method for e in fake.journal] == ["connect", "pause"]
    assert fake.paused
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None
    assert row.status == SandboxStatus.PAUSED
    assert row.agent_started_at is None and row.agent_pid is None


async def test_resume_paused_is_noop(committed_session_factory: Factory) -> None:
    await _ensure(committed_session_factory)
    fake = FakeSandbox(sandbox_id=PROVIDER_ID, paused=True)

    async with committed_session_factory() as session:
        await sandboxes.resume_sandbox(session, fake, PROVIDER_ID)

    assert fake.journal == []


async def test_resume_active_without_task_repairs(committed_session_factory: Factory) -> None:
    await _ensure(committed_session_factory)
    await _set_sandbox_status(committed_session_factory, SandboxStatus.ACTIVE)
    fake = FakeSandbox(sandbox_id=PROVIDER_ID, paused=False)

    async with committed_session_factory() as session:
        await sandboxes.resume_sandbox(session, fake, PROVIDER_ID)

    assert fake.paused
    async with committed_session_factory() as session:
        row = await sandboxes.sandbox_status(session, PROVIDER_ID)
    assert row is not None and row.status == SandboxStatus.PAUSED
