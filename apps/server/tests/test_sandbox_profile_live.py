"""Живые проверки sandbox-profile (tasks.md, раздел 5): песочница Novita, vault, память проекта.

Запуск вручную владельцем:
    uv run pytest -m live --tb=short <путь к этому файлу>

Без обязательных переменных тесты пропускаются. С флагом `-l` / `--showlocals` модуль не
выполняется: локальные переменные падающих тестов могут содержать ключи. Значения ключей
не печатаются; вывод команд проходит redaction, grep по диску ищет значения через env команд.

Порядок важен: модульная фикстура `prepared` один раз выполняет bootstrap (5.1 повторяет его),
остальные тесты работают с уже подготовленной песочницей. Каждый тест убирает свои файлы.

Переменные (см. также docs/deployment.md):
  LIVE_NOVITA_API_KEY, LIVE_NOVITA_SANDBOX_ID, LIVE_CLAUDE_CODE_OAUTH_TOKEN
  LIVE_NOVITA_DOMAIN (необязательная)
  VAULT_MCP_URL, VAULT_MCP_TOKEN          адрес и токен vault (https)
  LIVE_EMBEDDING_REF                      ссылка vault:<проект>/<сервис>/<имя> на ключ embeddings
  LIVE_REPO_ACCESS_REF (необязательная)   ссылка vault на ключ записи репозитория (repo.access_ref).
                                          Без неё клоны и fetch анонимные (только публичный
                                          репозиторий)
  LIVE_MEMORY_REF                         полный sha коммита memory-agent (D-51)
  LIVE_MEMORY_REPO (необязательная)       GitHub-репозиторий memory-agent
                                          (по умолчанию w1do/memory-agent)
  LIVE_REPO_PROVIDER (необязательная)     github | gitlab, по умолчанию gitlab (D-60)
  LIVE_REPO_PROJECT                       репозиторий workspace, например w1do/chistotyumen
  LIVE_DEFAULT_BRANCH (необязательная)    ветка для worktree, по умолчанию main
  TEST_DATABASE_URL или Docker            Postgres для теста 5.7

Авторизация git (D-52, D-60): заголовок с ключом уходит только на префикс адреса репозитория
workspace. Без LIVE_REPO_ACCESS_REF bootstrap и activate работают анонимно (публичный репозиторий).
Перед bootstrap проверяется, что репозиторий доступен без ключа (`git ls-remote`).
"""

import asyncio
import json
import logging
import os
import secrets as pysecrets
import shlex
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
import pytest_asyncio
from harness_server.adapters.novita import ExecResult, NovitaSandboxProvider, SandboxProvider
from harness_server.adapters.vault import McpSecretVault
from harness_server.config import HarnessConfig, RepoConfig, SandboxMemoryConfig, load_config
from harness_server.security.redaction import redact
from harness_server.services import git_access, sandboxes
from harness_server.services import secrets as secret_refs
from harness_server.services.agent_result import AgentRun, AgentState
from harness_server.services.sandboxes import AgentStartState
from harness_server.services.tasks import create_task
from harness_shared.tasks import TaskKind, TaskSource
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_CONFIG = REPO_ROOT / "config" / "harness.example.yaml"
BOOTSTRAP_PATH = REPO_ROOT / "deploy" / "sandbox" / "bootstrap.sh"
WORKSPACE_ID: Final = "demo"
DEFAULT_MEMORY_REPO: Final = "w1do/memory-agent"
DEFAULT_BRANCH: Final = "main"
REQUIRED_ENV: Final = (
    "LIVE_NOVITA_API_KEY",
    "LIVE_NOVITA_SANDBOX_ID",
    "LIVE_CLAUDE_CODE_OAUTH_TOKEN",
    "VAULT_MCP_URL",
    "VAULT_MCP_TOKEN",
    "LIVE_EMBEDDING_REF",
    "LIVE_MEMORY_REF",
    "LIVE_REPO_PROJECT",
)
# Многоходовая задача с инструментами (как в test_novita_live.py).
MULTI_TURN_PROMPT = (
    "Выполни по шагам, используя инструменты: 1) создай файл step1.txt с текстом one; "
    "2) прочитай step1.txt; 3) создай файл step2.txt с текстом two; "
    "4) прочитай step2.txt и выведи его содержимое."
)
# Задача 5.7 по решению владельца: правка README и коммит, без push.
COMMIT_PROMPT = (
    'Допиши в конец README.md строку 123 и сделай git commit с сообщением "live: 123". '
    "Ничего не пушь."
)
COMMIT_MESSAGE: Final = "live: 123"
ONE_WORD_PROMPT = "ответь одним словом: ok"
PROBE_SKILL: Final = "harness-probe"
PROBE_AGENT: Final = "harness-probe-agent"
EXEC_TIMEOUT_SEC: Final = 900
AGENT_TIMEOUT_MIN: Final = 60
AGENT_POLL_SEC: Final = 15
MEMORY_SERVICES: Final = ("qdrant", "typesense", "embeddings")


@dataclass(frozen=True)
class LiveEnv:
    """Переменные live-проверок. Значения не печатаются."""

    api_key: str = field(repr=False)
    sandbox_id: str
    oauth_token: str = field(repr=False)
    domain: str | None
    vault_url: str
    vault_token: str = field(repr=False)
    repo_ref: str | None
    embedding_ref: str
    memory_ref: str
    memory_repo: str
    repo_provider: str
    repo_project: str
    default_branch: str


@dataclass(frozen=True)
class Prepared:
    """Подготовленная песочница и ключи из vault для всех проверок модуля."""

    env: LiveEnv
    provider: SandboxProvider
    config: HarnessConfig
    script: str
    # None — публичный репозиторий без ключа записи (LIVE_REPO_ACCESS_REF не задан).
    gitlab: SecretStr | None
    embedding: SecretStr
    home: str
    # Значения, которые нельзя показывать: redaction вывода команд и проверки на диске.
    secret_values: tuple[str, ...] = field(repr=False)


def _safe(text: str, secret_values: Sequence[str]) -> str:
    """Хвост текста для сообщения проверки, с заменой значений секретов."""
    return redact(text, extra_values=secret_values)[-2000:]


def _live_env() -> LiveEnv:
    """Читает переменные; без обязательных — пропуск с именами переменных, не значениями."""
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        pytest.skip("нужны переменные: " + ", ".join(missing))
    return LiveEnv(
        api_key=os.environ["LIVE_NOVITA_API_KEY"],
        sandbox_id=os.environ["LIVE_NOVITA_SANDBOX_ID"],
        oauth_token=os.environ["LIVE_CLAUDE_CODE_OAUTH_TOKEN"],
        domain=os.environ.get("LIVE_NOVITA_DOMAIN") or None,
        vault_url=os.environ["VAULT_MCP_URL"],
        vault_token=os.environ["VAULT_MCP_TOKEN"],
        repo_ref=os.environ.get("LIVE_REPO_ACCESS_REF") or None,
        embedding_ref=os.environ["LIVE_EMBEDDING_REF"],
        memory_ref=os.environ["LIVE_MEMORY_REF"],
        memory_repo=os.environ.get("LIVE_MEMORY_REPO") or DEFAULT_MEMORY_REPO,
        repo_provider=os.environ.get("LIVE_REPO_PROVIDER") or "gitlab",
        repo_project=os.environ["LIVE_REPO_PROJECT"],
        default_branch=os.environ.get("LIVE_DEFAULT_BRANCH") or DEFAULT_BRANCH,
    )


def _live_config(env: LiveEnv) -> HarnessConfig:
    """Конфиг из примера с живыми значениями: песочница, память, репозиторий workspace (D-60)."""
    base = load_config(EXAMPLE_CONFIG)
    repo = RepoConfig.model_validate(
        {"provider": env.repo_provider, "project": env.repo_project, "access_ref": env.repo_ref}
    )
    workspace = base.workspaces[0].model_copy(
        update={
            "id": WORKSPACE_ID,
            "repo": repo,
            "default_branch": env.default_branch,
        }
    )
    sandbox = base.sandbox.model_copy(
        update={
            "provider_id": env.sandbox_id,
            "memory": SandboxMemoryConfig(
                ref=env.memory_ref,
                repo=env.memory_repo,
                embedding_ref=env.embedding_ref,
            ),
        }
    )
    return base.model_copy(update={"workspaces": [workspace], "sandbox": sandbox})


@pytest.fixture(scope="session", autouse=True)
def _refuse_showlocals(request: pytest.FixtureRequest) -> None:
    """С --showlocals pytest печатает локальные переменные падающих тестов: там могут быть ключи."""
    if request.config.getoption("showlocals", default=False):
        pytest.skip("live-проверки не запускаются с --showlocals (-l): используйте --tb=short")


@pytest.fixture(scope="session")
def live_env() -> LiveEnv:
    return _live_env()


def _anonymous_reachable(url: str) -> bool:
    """Репозиторий доступен без ключа: ls-remote без помощников учётных данных и без запроса."""
    env = {**os.environ, "GIT_ASKPASS": "/bin/false", "GIT_TERMINAL_PROMPT": "0"}
    env.pop("GITLAB_TOKEN", None)
    completed = subprocess.run(
        ["git", "-c", "credential.helper=", "ls-remote", "--heads", url],
        capture_output=True,
        check=False,
        env=env,
        timeout=180,
    )
    return completed.returncode == 0


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def prepared(live_env: LiveEnv) -> AsyncIterator[Prepared]:
    """Ключи из vault тем же путём, что в проде, и первый bootstrap с памятью."""
    provider = NovitaSandboxProvider(api_key=live_env.api_key, domain=live_env.domain)
    vault = McpSecretVault(live_env.vault_url, SecretStr(live_env.vault_token))
    # Без LIVE_REPO_ACCESS_REF ключ не нужен: публичный репозиторий клонируется анонимно (D-60).
    gitlab: SecretStr | None = None
    if live_env.repo_ref is not None:
        gitlab = await secret_refs.resolve(vault, live_env.repo_ref, fallback=None)
        if gitlab is None:
            pytest.fail("vault не вернул ключ репозитория")
    embedding = await secret_refs.resolve(vault, live_env.embedding_ref, fallback=None)
    if embedding is None:
        pytest.fail("vault не вернул ключ embeddings")
    config = _live_config(live_env)
    if not _anonymous_reachable(git_access.clone_url(config.workspaces[0].repo)):
        pytest.fail(
            "репозиторий workspace недоступен без ключа: сделайте его публичным или проверьте адрес"
        )
    script = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    # Заголовок Basic и его base64-часть — секреты, если задан ключ репозитория (D-52, D-60).
    gitlab_values: tuple[str, ...] = ()
    if gitlab is not None:
        gitlab_values = git_access.git_auth_secret_values(
            config.workspaces[0].repo.provider, gitlab.get_secret_value()
        )
        gitlab_values = (gitlab.get_secret_value(), *gitlab_values)
    values = (*gitlab_values, embedding.get_secret_value(), live_env.oauth_token)
    result = await sandboxes.bootstrap(
        provider,
        live_env.sandbox_id,
        config,
        script=script,
        repo_tokens={WORKSPACE_ID: gitlab} if gitlab is not None else {},
        memory_ref=live_env.memory_ref,
        memory_repo=live_env.memory_repo,
        embedding_key=embedding,
    )
    output = _safe(result.stdout + result.stderr, values)
    code = result.exit_code
    assert code == 0, f"первый bootstrap завершился с кодом {code}\n{output}"
    home = await sandboxes.home_dir(provider, live_env.sandbox_id)
    yield Prepared(
        env=live_env,
        provider=provider,
        config=config,
        script=script,
        gitlab=gitlab,
        embedding=embedding,
        home=home,
        secret_values=values,
    )


def _labelled_secrets(p: Prepared) -> list[tuple[str, str]]:
    """Имя и значение каждого секрета, который проверяется на диске (ключ GitLab — если задан)."""
    pairs = [
        ("ключа embeddings", p.embedding.get_secret_value()),
        ("OAuth-токена", p.env.oauth_token),
    ]
    if p.gitlab is not None:
        pairs.append(("ключа репозитория", p.gitlab.get_secret_value()))
    return pairs


async def _run(
    p: Prepared,
    cmd: str,
    *,
    envs: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout_s: int = EXEC_TIMEOUT_SEC,
) -> ExecResult:
    return await p.provider.exec(p.env.sandbox_id, cmd, envs=envs, cwd=cwd, timeout_s=timeout_s)


async def _workdir(p: Prepared) -> str:
    """Пустой каталог в песочнице с mcp.json без серверов: изоляция от настроек репозитория."""
    base = f"/tmp/harness-profile-live-{uuid.uuid4().hex}"
    try:
        await _run(p, f"mkdir -p {shlex.quote(base)}")
        await p.provider.write_file(p.env.sandbox_id, f"{base}/mcp.json", '{"mcpServers": {}}\n')
    except BaseException:
        # Частично созданный каталог убираем, иначе он остаётся в песочнице после сбоя (L4).
        await _run(p, f"rm -rf {shlex.quote(base)}")
        raise
    return base


async def _remove(p: Prepared, path: str) -> None:
    await _run(p, f"rm -rf {shlex.quote(path)}")


def _claude_command(prompt: str, *, max_turns: int, mcp_config: str) -> str:
    """Команда claude как в run.sh: без ANTHROPIC_*, user-настройки, пустой MCP."""
    return (
        "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; "
        f"claude -p {shlex.quote(prompt)} --output-format stream-json --verbose "
        f"--max-turns {max_turns} --permission-mode bypassPermissions "
        "--setting-sources user --strict-mcp-config "
        f"--mcp-config {shlex.quote(mcp_config)}"
    )


def _events(stdout: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]


def _result_event(stdout: str) -> dict[str, Any]:
    results = [event for event in _events(stdout) if event.get("type") == "result"]
    assert results, "в потоке нет события result"
    return results[-1]


def _status_is_ok(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() == "ok"
    if isinstance(value, dict):
        return str(value.get("status", value.get("ok", ""))).lower() in {"ok", "true"}
    return value is True


def _component_ok(payload: object, name: str) -> bool:
    """Ищет компонент memory status по имени и проверяет его статус.

    Схема вывода `memory status --json` в проекте не зафиксирована, поэтому поиск мягкий: по ключу
    или полю name, со статусом ok. Если схема другая — тест покажет это по сообщению.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if name in str(key).lower() and _status_is_ok(value):
                return True
            if _component_ok(value, name):
                return True
    elif isinstance(payload, list):
        for item in payload:
            named = isinstance(item, dict) and name in str(item.get("name", "")).lower()
            if named and _status_is_ok(item):
                return True
            if _component_ok(item, name):
                return True
    return False


async def _memory_status(p: Prepared) -> object:
    """memory status --json по клону workspace; ключ embeddings — только в env команды."""
    repo = f"{p.home}/work/{WORKSPACE_ID}"
    result = await _run(
        p,
        f"memory status --json --path {shlex.quote(repo)}",
        envs={"EMBEDDING_API_KEY": p.embedding.get_secret_value()},
        timeout_s=600,
    )
    code = result.exit_code
    assert code == 0, _safe(result.stderr, p.secret_values)
    text = result.stdout
    try:
        return json.loads(text)
    except ValueError:
        pytest.fail("вывод memory status --json не является JSON")


def _assert_services_ok(payload: object) -> None:
    for component in MEMORY_SERVICES:
        ok = _component_ok(payload, component)
        assert ok, f"компонент memory {component} не в статусе ok"


# --- 5.1 ---------------------------------------------------------------------------------------


async def test_5_1_second_bootstrap_is_idempotent(prepared: Prepared) -> None:
    spec = f"github:{prepared.env.memory_repo}#{prepared.env.memory_ref}"
    result = await sandboxes.bootstrap(
        prepared.provider,
        prepared.env.sandbox_id,
        prepared.config,
        script=prepared.script,
        repo_tokens={WORKSPACE_ID: prepared.gitlab} if prepared.gitlab is not None else {},
        memory_ref=prepared.env.memory_ref,
        memory_repo=prepared.env.memory_repo,
        embedding_key=prepared.embedding,
    )
    output = _safe(result.stdout + result.stderr, prepared.secret_values)

    code = result.exit_code
    assert code == 0, f"повторный bootstrap завершился с кодом {code}\n{output}"
    # Ничего не ставится и не клонируется заново: в выводе нет строк установки (ставлю/клонирую).
    assert "ставлю" not in output, output
    assert "клонирую" not in output, output
    assert "уже установлен: Node" in output, output
    assert f"уже установлен: {spec}" in output, output

    marker = await _run(
        prepared, f"cat {shlex.quote(prepared.home + '/.harness/memory/installed-ref')}"
    )
    marker_code = marker.exit_code
    assert marker_code == 0, "не читается маркер installed-ref"
    marker_text = marker.stdout.strip()
    assert marker_text == spec, "маркер installed-ref не совпадает с закреплённым коммитом"

    # Бинарь memory доступен пользователю песочницы, не только root (D-51: umask в установке).
    help_run = await _run(prepared, "memory --help")
    help_code = help_run.exit_code
    assert help_code == 0, _safe(help_run.stderr, prepared.secret_values)


# --- 5.2 ---------------------------------------------------------------------------------------


async def test_5_2_memory_status_ok_and_key_not_on_disk(prepared: Prepared) -> None:
    _assert_services_ok(await _memory_status(prepared))

    # Значения ищутся через env команды; выводятся только пути файлов, сами значения — нет.
    for label, value in _labelled_secrets(prepared):
        found = await _run(
            prepared,
            'grep -rlF -- "$CHECK_VALUE" "$HOME" 2>/dev/null; true',
            envs={"CHECK_VALUE": value},
        )
        found_paths = found.stdout.strip()
        assert found_paths == "", f"значение {label} найдено на диске песочницы"


# --- 5.3 ---------------------------------------------------------------------------------------


async def test_5_3_agent_runs_multi_turn_with_services_up_and_no_oom(prepared: Prepared) -> None:
    before = await _run(prepared, "free -m")
    print(f"free -m до задачи:\n{before.stdout}")  # для отчёта владельца: ресурсы песочницы
    # dmesg может быть недоступен без прав: тогда счётчик 0 и проверка формальна (см. отчёт).
    oom = await _run(prepared, 'dmesg 2>/dev/null | grep -ci "out of memory\\|oom-kill" || true')
    oom_count = oom.stdout.strip()
    assert oom_count in {"", "0"}, "в dmesg есть записи OOM"

    workdir = await _workdir(prepared)
    try:
        result = await _run(
            prepared,
            _claude_command(MULTI_TURN_PROMPT, max_turns=20, mcp_config=f"{workdir}/mcp.json"),
            envs={"CLAUDE_CODE_OAUTH_TOKEN": prepared.env.oauth_token},
            cwd=workdir,
        )
        subtype = _result_event(result.stdout).get("subtype")
        assert subtype == "success", "агент не завершился с subtype success"
        _assert_services_ok(await _memory_status(prepared))
    finally:
        await _remove(prepared, workdir)
    after = await _run(prepared, "free -m")
    print(f"free -m после задачи:\n{after.stdout}")


# --- 5.4 ---------------------------------------------------------------------------------------


def test_5_4_worktree_isolation_test_passes(live_env: LiveEnv) -> None:
    """Изоляция не изменилась: запускает тест из test_novita_live.py отдельным процессом.

    Вывод pytest не печатается: он может содержать значения, которые тест выводит в сообщении.
    """
    module = "apps/server/tests/test_novita_live.py"
    node = f"{module}::test_live_worktree_hooks_and_repo_mcp_are_not_loaded"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "live", "-q", "-p", "no:cacheprovider", node],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=EXEC_TIMEOUT_SEC * 2,
    )
    assert completed.returncode == 0, (
        "тест изоляции test_live_worktree_hooks_and_repo_mcp_are_not_loaded не прошёл; "
        "запустите его отдельно с теми же переменными, чтобы увидеть подробности"
    )


# --- 5.5 ---------------------------------------------------------------------------------------


async def test_5_5_pause_resume_keeps_docker_and_memory(prepared: Prepared) -> None:
    # Пауза и возобновление через провайдер (как sandbox pause/resume, без записи в БД).
    sandbox_id = prepared.env.sandbox_id
    await prepared.provider.pause(sandbox_id)
    try:
        await prepared.provider.connect(sandbox_id)
        ensure = await _run(
            prepared,
            f"bash {shlex.quote(prepared.home + '/.harness/bin/ensure-docker.sh')}",
            timeout_s=600,
        )
        ensure_code = ensure.exit_code
        assert ensure_code == 0, _safe(ensure.stderr, prepared.secret_values)
        _assert_services_ok(await _memory_status(prepared))
    finally:
        # Возобновление в finally: следующие тесты не начнутся на паузе, даже если проверка упала.
        await prepared.provider.connect(sandbox_id)


# --- 5.6 ---------------------------------------------------------------------------------------

SKILL_TEXT = (
    "---\n"
    f"name: {PROBE_SKILL}\n"
    "description: Тестовый skill для live-проверки видимости (sandbox-profile 5.6).\n"
    "---\n"
    "Тестовый skill. Ничего не делать.\n"
)
AGENT_TEXT = (
    "---\n"
    f"name: {PROBE_AGENT}\n"
    "description: Тестовый агент для live-проверки видимости (sandbox-profile 5.6).\n"
    "---\n"
    "Тестовый агент. Ничего не делать.\n"
)


def _names(items: object) -> set[str]:
    if not isinstance(items, list):
        return set()
    names: set[str] = set()
    for item in items:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def _has(names: set[str], probe: str) -> bool:
    return any(name == probe or name.endswith(f":{probe}") for name in names)


async def test_5_6_probe_skill_and_agent_visible_with_user_settings(prepared: Prepared) -> None:
    skill_dir = f"{prepared.home}/.claude/skills/{PROBE_SKILL}"
    agents_dir = f"{prepared.home}/.claude/agents"
    agent_file = f"{agents_dir}/{PROBE_AGENT}.md"
    sandbox_id = prepared.env.sandbox_id
    workdir = await _workdir(prepared)
    try:
        await _run(prepared, f"rm -rf {shlex.quote(skill_dir)}; rm -f {shlex.quote(agent_file)}")
        await _run(prepared, f"mkdir -p {shlex.quote(skill_dir)} {shlex.quote(agents_dir)}")
        await prepared.provider.write_file(sandbox_id, f"{skill_dir}/SKILL.md", SKILL_TEXT)
        await prepared.provider.write_file(sandbox_id, agent_file, AGENT_TEXT)

        result = await _run(
            prepared,
            _claude_command(ONE_WORD_PROMPT, max_turns=1, mcp_config=f"{workdir}/mcp.json"),
            envs={"CLAUDE_CODE_OAUTH_TOKEN": prepared.env.oauth_token},
            cwd=workdir,
        )
        init = [e for e in _events(result.stdout) if e.get("subtype") == "init"]
        assert init, "в потоке нет system/init"
        skills = _names(init[0].get("skills")) | _names(init[0].get("slash_commands"))
        agents = _names(init[0].get("agents"))
        assert _has(skills, PROBE_SKILL), f"skill {PROBE_SKILL} не виден агенту"
        assert _has(agents, PROBE_AGENT), f"агент {PROBE_AGENT} не виден агенту"
    finally:
        await _run(prepared, f"rm -rf {shlex.quote(skill_dir)}; rm -f {shlex.quote(agent_file)}")
        await _remove(prepared, workdir)


# --- 5.7 ---------------------------------------------------------------------------------------


async def _wait_for_agent(
    p: Prepared, task: Any, started_at: datetime, pid: int | None
) -> AgentRun:
    """Опрос агента до завершения (как worker): RUNNING — ждём, иначе итог."""
    secrets = p.secret_values
    while True:
        run = await sandboxes.wait_agent(
            p.provider,
            p.env.sandbox_id,
            task,
            started_at=started_at,
            pid=pid,
            timeout_min=AGENT_TIMEOUT_MIN,
            now=datetime.now(UTC),
            secrets=secrets,
        )
        if run.state is not AgentState.RUNNING:
            return run
        await asyncio.sleep(AGENT_POLL_SEC)


async def test_5_7_activation_with_memory_commits_in_worktree(
    prepared: Prepared,
    committed_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Активация с памятью, агент правит README и коммитит в worktree, без push."""
    caplog.set_level(logging.WARNING, logger="harness_server.services.sandboxes")
    p = prepared
    sandbox_id = p.env.sandbox_id
    workspace = p.config.workspaces[0]
    async with committed_session_factory() as session:
        await sandboxes.ensure_sandbox(session, p.config)
    async with committed_session_factory() as session:
        task = await create_task(
            session,
            kind=TaskKind.IMPLEMENT,
            text="live-проверка sandbox-profile 5.7",
            source=TaskSource.API,
            known_workspace_ids=[WORKSPACE_ID],
            workspace_id=WORKSPACE_ID,
        )
    try:
        await sandboxes.activate(
            p.provider,
            sandbox_id,
            task,
            base_ref=workspace.default_branch,
            timeout_min=AGENT_TIMEOUT_MIN,
            repo=p.config.workspaces[0].repo,
            repo_token=p.gitlab,
            default_branch=workspace.default_branch,
            memory_envs={"EMBEDDING_API_KEY": p.embedding.get_secret_value()},
        )
        sync_failed = "memory sync failed" in caplog.text
        assert not sync_failed, "memory sync при активации не прошёл (см. лог worker)"

        async with committed_session_factory() as session:
            start = await sandboxes.run_agent(
                session,
                p.provider,
                sandbox_id,
                task,
                prompt=COMMIT_PROMPT,
                max_turns=20,
                timeout_min=AGENT_TIMEOUT_MIN,
                secret_key=SecretStr(pysecrets.token_hex(32)),
                oauth_token=SecretStr(p.env.oauth_token),
                agents_flow_url="https://harness.invalid/mcp",
                memory_enabled=True,
                # Как диспетчер: автор коммитов агента — env запуска (sandbox.git_author).
                extra_envs=sandboxes.git_author_env(p.config.sandbox.git_author),
            )
        started = start.state is AgentStartState.STARTED
        assert started, "агент не запущен"
        async with committed_session_factory() as session:
            info = await sandboxes.agent_run_info(session, sandbox_id)
        agent_pid = info.pid
        if agent_pid is None:
            pytest.fail("pid агента не записан")

        # HARNESS_MEMORY_PROJECT читаем из env процесса сразу после запуска. Выводится только
        # имя переменной и путь клона: других значений из env не печатаем.
        environ = await _run(
            p,
            f"tr '\\0' '\\n' < /proc/{int(agent_pid)}/environ 2>/dev/null | "
            "grep '^HARNESS_MEMORY_PROJECT=' || true",
            timeout_s=60,
        )
        expected = f"HARNESS_MEMORY_PROJECT={p.home}/work/{WORKSPACE_ID}"
        seen = environ.stdout.strip()
        if seen:
            project_ok = seen == expected
            assert project_ok, "HARNESS_MEMORY_PROJECT с другим путём"
        else:
            # Агент уже завершился: env не прочитать. Проверка HARNESS_MEMORY_PROJECT пропущена,
            # явно и с сообщением; остальные проверки этого теста идут как обычно.
            print(
                "ПРОПУСК проверки HARNESS_MEMORY_PROJECT: агент завершился до чтения /proc; "
                "проверяем только, что ключи не попали в run.sh и run.json"
            )
        # Ключи не должны попадать в файлы запуска (значения — через env grep, не через argv).
        task_dir = shlex.quote(f"{p.home}/.harness/tasks/{task.id}")
        for label, value in _labelled_secrets(p):
            leak = await _run(
                p,
                f'grep -lF -- "$CHECK_VALUE" {task_dir}/run.sh {task_dir}/run.json '
                "2>/dev/null; true",
                envs={"CHECK_VALUE": value},
            )
            leaked = leak.stdout.strip() != ""
            assert not leaked, f"значение {label} найдено в run.sh или run.json"

        started_at = info.started_at or datetime.now(UTC)
        run = await _wait_for_agent(p, task, started_at, info.pid)
        finished = run.state is AgentState.FINISHED
        assert finished, "агент не завершился штатно (статус из wait_agent, см. ленту задачи)"
        succeeded = run.succeeded
        assert succeeded, "агент завершился с ошибкой (код выхода или subtype, см. ленту задачи)"

        worktree = sandboxes.worktree_dir(p.home, task.id)
        subject = await _run(p, f"git -C {shlex.quote(worktree)} log -1 --format=%s")
        subject_ok = subject.stdout.strip() == COMMIT_MESSAGE
        assert subject_ok, "последний коммит worktree не 'live: 123'"
        diff = await _run(p, f"git -C {shlex.quote(worktree)} show HEAD -- README.md")
        diff_ok = "+123" in diff.stdout.splitlines()
        assert diff_ok, "в README.md коммита нет добавленной строки 123"
    finally:
        async with committed_session_factory() as session:
            await sandboxes.cleanup_task(
                session, p.provider, sandbox_id, task, secrets=p.secret_values
            )
            await sandboxes.release_sandbox(session, p.provider, sandbox_id)
