"""Живая проверка песочницы Novita и Claude Code в ней: реальный ключ, по умолчанию пропуск.

Запуск (владелец, вручную): LIVE_NOVITA_API_KEY=… LIVE_NOVITA_SANDBOX_ID=… \
LIVE_CLAUDE_CODE_OAUTH_TOKEN=… uv run pytest -m live apps/server/tests/test_novita_live.py
Песочница должна быть подготовлена deploy/sandbox/bootstrap.sh (claude в PATH). Без переменных
тесты пропускаются. Значения ключей не печатаются и в тексты ошибок не попадают.

Отклонения от design 1.4: вместо ~/.harness/mcp.json тест создаёт пустой mcp.json во временном
каталоге (ключ --mcp-config), так как bootstrap-файл зависит от состояния песочницы. Запуск агента
через run_agent (задача 3.5) заменит этот каталог боевым worktree.
"""

import json
import os
import shlex
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from harness_server.adapters.novita import NovitaSandboxProvider, SandboxProvider

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]

# Многоходовая задача с инструментами: без tool-use ход в песочнице укладывается в один вызов.
MULTI_TURN_PROMPT = (
    "Выполни по шагам, используя инструменты: 1) создай файл step1.txt с текстом one; "
    "2) прочитай step1.txt; 3) создай файл step2.txt с текстом two; "
    "4) прочитай step2.txt и выведи его содержимое."
)
ONE_WORD_PROMPT = "ответь одним словом: ok"
EXEC_TIMEOUT_SEC = 600
TRAP_HOOK_NAME = "hook-fired"
TRAP_MCP_NAME = "trap"


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


def _claude_command(prompt: str, *, max_turns: int, mcp_config: str) -> str:
    """Команда как в run.sh (design 4–5): без ANTHROPIC_* и с изоляцией от настроек репозитория."""
    return (
        "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; "
        f"claude -p {shlex.quote(prompt)} --output-format stream-json --verbose "
        f"--max-turns {max_turns} --permission-mode bypassPermissions "
        "--setting-sources user --strict-mcp-config "
        f"--mcp-config {shlex.quote(mcp_config)}"
    )


def _events(stdout: str) -> list[dict[str, Any]]:
    """JSON-события stream-json; строки, не являющиеся объектом, пропускаются."""
    return [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]


def _result_event(stdout: str) -> dict[str, Any]:
    results = [event for event in _events(stdout) if event.get("type") == "result"]
    assert results, "в потоке нет события result"
    return results[-1]


@pytest.fixture
async def workdir(provider: SandboxProvider, sandbox_id: str) -> AsyncIterator[str]:
    """Временный каталог в песочнице: worktree и mcp.json; удаляется после теста."""
    base = f"/tmp/harness-live-{uuid.uuid4().hex}"
    await provider.exec(sandbox_id, f"mkdir -p {shlex.quote(base + '/worktree/.claude')}")
    await provider.write_file(sandbox_id, f"{base}/mcp.json", '{"mcpServers": {}}\n')
    try:
        yield base
    finally:
        await provider.exec(sandbox_id, f"rm -rf {shlex.quote(base)}")


@pytest.fixture
def provider() -> SandboxProvider:
    api_key, _, _, domain = _live_settings()
    return NovitaSandboxProvider(api_key=api_key, domain=domain)


@pytest.fixture
def sandbox_id() -> str:
    _, sandbox, _, _ = _live_settings()
    return sandbox


async def test_live_exec_write_read_pause_connect(
    provider: SandboxProvider, sandbox_id: str
) -> None:
    path = f"/tmp/harness-live-{uuid.uuid4().hex}.txt"

    echo = await provider.exec(sandbox_id, "echo live-ok")
    assert echo.exit_code == 0
    assert "live-ok" in echo.stdout

    failed = await provider.exec(sandbox_id, "exit 3")
    assert failed.exit_code == 3

    await provider.write_file(sandbox_id, path, "payload\n")
    assert await provider.read_file(sandbox_id, path) == "payload\n"
    assert await provider.read_file(sandbox_id, path + ".missing") is None

    # Пауза и возобновление сохраняют файлы (mvp-01, один короткий цикл).
    await provider.pause(sandbox_id)
    await provider.connect(sandbox_id)
    assert await provider.read_file(sandbox_id, path) == "payload\n"
    await provider.exec(sandbox_id, f"rm -f {path}")


async def test_live_claude_stream_json_reports_result_event(
    provider: SandboxProvider, sandbox_id: str, workdir: str
) -> None:
    _, _, oauth_token, _ = _live_settings()
    result = await provider.exec(
        sandbox_id,
        _claude_command(ONE_WORD_PROMPT, max_turns=1, mcp_config=f"{workdir}/mcp.json"),
        envs={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token},
        timeout_s=EXEC_TIMEOUT_SEC,
    )

    assert _result_event(result.stdout)["subtype"] in {"success", "error_max_turns"}


async def test_live_max_turns_one_on_multi_turn_task_is_error_max_turns(
    provider: SandboxProvider, sandbox_id: str, workdir: str
) -> None:
    _, _, oauth_token, _ = _live_settings()
    result = await provider.exec(
        sandbox_id,
        _claude_command(MULTI_TURN_PROMPT, max_turns=1, mcp_config=f"{workdir}/mcp.json"),
        envs={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token},
        timeout_s=EXEC_TIMEOUT_SEC,
    )

    assert _result_event(result.stdout)["subtype"] == "error_max_turns"


async def test_live_multi_turn_tool_use_records_message_id_and_usage(
    provider: SandboxProvider, sandbox_id: str, workdir: str
) -> None:
    _, _, oauth_token, _ = _live_settings()
    worktree = f"{workdir}/worktree"
    result = await provider.exec(
        sandbox_id,
        _claude_command(MULTI_TURN_PROMPT, max_turns=20, mcp_config=f"{workdir}/mcp.json"),
        envs={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token},
        cwd=worktree,
        timeout_s=EXEC_TIMEOUT_SEC,
    )

    events = _events(result.stdout)
    final = _result_event(result.stdout)
    assert final["subtype"] == "success"
    # Инструменты реально выполнены: файлы созданы агентом внутри worktree.
    assert await provider.read_file(sandbox_id, f"{worktree}/step1.txt") is not None
    assert await provider.read_file(sandbox_id, f"{worktree}/step2.txt") is not None

    # Поведение, которое фиксирует design 1.4 и D-37: message.id на ход и result.usage.
    message_ids = [
        event["message"]["id"]
        for event in events
        if event.get("type") == "assistant" and "id" in event.get("message", {})
    ]
    usage = final.get("usage")
    assert isinstance(usage, dict) and "input_tokens" in usage
    print(  # значения нужны владельцу для отчёта по D-37
        f"message.id: ходов={len(message_ids)} уникальных={len(set(message_ids))}; "
        f"result.usage={usage}; num_turns={final.get('num_turns')}"
    )


async def test_live_worktree_hooks_and_repo_mcp_are_not_loaded(
    provider: SandboxProvider, sandbox_id: str, workdir: str
) -> None:
    _, _, oauth_token, _ = _live_settings()
    worktree = f"{workdir}/worktree"
    hook_marker = f"{workdir}/{TRAP_HOOK_NAME}"
    mcp_marker = f"{workdir}/{TRAP_MCP_NAME}"
    # Ловушка из репозитория: hook из settings проекта и MCP-сервер из .mcp.json worktree.
    settings = {
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": f"touch {hook_marker}"}]}]
        }
    }
    repo_mcp = {"mcpServers": {TRAP_MCP_NAME: {"type": "stdio", "command": f"touch {mcp_marker}"}}}
    await provider.write_file(sandbox_id, f"{worktree}/.claude/settings.json", json.dumps(settings))
    await provider.write_file(sandbox_id, f"{worktree}/.mcp.json", json.dumps(repo_mcp))

    result = await provider.exec(
        sandbox_id,
        _claude_command(ONE_WORD_PROMPT, max_turns=1, mcp_config=f"{workdir}/mcp.json"),
        envs={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token},
        cwd=worktree,
        timeout_s=EXEC_TIMEOUT_SEC,
    )

    assert await provider.read_file(sandbox_id, hook_marker) is None
    assert await provider.read_file(sandbox_id, mcp_marker) is None
    init_events = [e for e in _events(result.stdout) if e.get("subtype") == "init"]
    assert init_events, "в потоке нет system/init"
    servers = init_events[0].get("mcp_servers", [])
    names = {s.get("name") if isinstance(s, dict) else s for s in servers}
    assert TRAP_MCP_NAME not in names


async def test_live_token_is_not_left_on_disk(
    provider: SandboxProvider, sandbox_id: str, workdir: str
) -> None:
    _, _, oauth_token, _ = _live_settings()
    worktree = f"{workdir}/worktree"
    await provider.exec(
        sandbox_id,
        _claude_command(ONE_WORD_PROMPT, max_turns=1, mcp_config=f"{workdir}/mcp.json"),
        envs={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token},
        cwd=worktree,
        timeout_s=EXEC_TIMEOUT_SEC,
    )

    # Значение передаётся в grep только через env: в тексте команды его нет. Ищем в ~ и worktree.
    search = await provider.exec(
        sandbox_id,
        f'grep -rlF -- "$CHECK_VALUE" "$HOME" {shlex.quote(workdir)} 2>/dev/null; true',
        envs={"CHECK_VALUE": oauth_token},
        timeout_s=EXEC_TIMEOUT_SEC,
    )
    # Выводятся только пути, сам токен не печатается.
    assert search.stdout.strip() == ""
