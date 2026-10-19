"""Подготовка песочницы через services/sandboxes.bootstrap на FakeSandbox (mvp-06, 2.3).

Без сети и без GitLab. Проверяются команда и её аргументы из конфига, передача токена только в env
и отсутствие значения токена в записанном скрипте и в файлах песочницы.
"""

import os
import re
import subprocess
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from harness_server.adapters.novita import ExecResult, FakeSandbox, SandboxUnavailable
from harness_server.config import load_config
from harness_server.services.sandboxes import BOOTSTRAP_SCRIPT_PREFIX, bootstrap
from pydantic import SecretStr

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_CONFIG = REPO_ROOT / "config" / "harness.example.yaml"
SCRIPT_PATH = REPO_ROOT / "deploy" / "sandbox" / "bootstrap.sh"
SANDBOX_ID = "sbx-test-1"
# Тестовое значение в формате токена GitLab; настоящий токен здесь не используется.
GITLAB_TOKEN = "glpat-test-token-0123456789abcdef"
# Фиктивный sha для тестов (D-51): настоящий закреплённый коммит — только в harness.yaml и D-51.
MEMORY_REF = "0123456789abcdef0123456789abcdef01234567"
MEMORY_REPO = "w1do/memory-agent"

EXPECTED_ARGS = (
    "--claude-version 2.1.292 --openspec-version 1.14.3 "
    "--gitlab-url https://gitlab.com demo=https://gitlab.com/group/demo.git"
)
SCRIPT_PATH_RE = re.compile(r"/tmp/harness-bootstrap-[0-9a-f]{32}\.sh")


def _written_script_paths(sandbox: FakeSandbox) -> list[str]:
    """Пути, по которым bootstrap записал скрипт (уникальные на каждый запуск, D-52)."""
    return [e.cmd for e in sandbox.journal if e.method == "write_file" and e.cmd is not None]


def _script_path(sandbox: FakeSandbox) -> str:
    paths = _written_script_paths(sandbox)
    assert len(paths) == 1
    assert SCRIPT_PATH_RE.fullmatch(paths[0]) is not None
    return paths[0]


class _FailingBashSandbox(FakeSandbox):
    """Команда bootstrap падает SDK-ошибкой; очистка (rm) проходит. Журнал пишет FakeSandbox."""

    async def exec(
        self,
        sandbox_id: str,
        cmd: str,
        *,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float = 60,
    ) -> ExecResult:
        if cmd.startswith("bash "):
            raise SandboxUnavailable("sdk_error")
        return await super().exec(sandbox_id, cmd, envs=envs, cwd=cwd, timeout_s=timeout_s)


class _FailingRmSandbox(FakeSandbox):
    """rm падает: ошибка очистки не должна менять исход bootstrap."""

    async def exec(
        self,
        sandbox_id: str,
        cmd: str,
        *,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float = 60,
    ) -> ExecResult:
        if cmd.startswith("rm -f "):
            raise SandboxUnavailable("sdk_error")
        return await super().exec(sandbox_id, cmd, envs=envs, cwd=cwd, timeout_s=timeout_s)


async def test_bootstrap_writes_script_and_runs_it_with_config_arguments() -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID)

    result = await bootstrap(
        sandbox,
        SANDBOX_ID,
        config,
        script="#!/usr/bin/env bash\necho ok\n",
        gitlab_token=SecretStr(GITLAB_TOKEN),
    )

    assert result == ExecResult(exit_code=0, stdout="", stderr="")
    # Скрипт записан по уникальному абсолютному пути и запущен с ним же (D-52, ревью).
    path = _script_path(sandbox)
    assert sandbox.files_containing("echo ok") == [path]
    execs = [entry for entry in sandbox.journal if entry.method == "exec" and entry.cmd]
    assert execs[0].cmd == f"bash {path} {EXPECTED_ARGS}"
    assert execs[0].env_keys == ("GITLAB_TOKEN", "GIT_TERMINAL_PROMPT", "HARNESS_SANDBOX_BOOTSTRAP")


async def test_bootstrap_passes_token_only_in_command_env() -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID)

    await bootstrap(
        sandbox,
        SANDBOX_ID,
        config,
        script=SCRIPT_PATH.read_text(encoding="utf-8"),
        gitlab_token=SecretStr(GITLAB_TOKEN),
    )

    assert sandbox.received_env("GITLAB_TOKEN") == GITLAB_TOKEN
    assert all(GITLAB_TOKEN not in entry.cmd for entry in sandbox.journal if entry.cmd)
    assert sandbox.files_containing(GITLAB_TOKEN) == []


async def test_bootstrap_connects_before_writing() -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID, paused=True)

    await bootstrap(
        sandbox,
        SANDBOX_ID,
        config,
        script="echo\n",
        gitlab_token=SecretStr(GITLAB_TOKEN),
    )

    assert sandbox.paused is False
    # После запуска скрипт удаляется отдельной командой rm (D-52, ревью).
    assert [entry.method for entry in sandbox.journal] == ["connect", "write_file", "exec", "exec"]


def test_repo_bootstrap_script_is_executable_and_has_no_secret_values() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert os.access(SCRIPT_PATH, os.X_OK)
    assert GITLAB_TOKEN not in text
    # Шаблоны известных токенов: в скрипте допустима только ссылка на переменную, не значение.
    for prefix in ("glpat-", "sk-ant-", "nk-"):
        assert prefix not in text


async def test_memory_ref_goes_to_script_args_and_key_only_to_env() -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID)
    embedding = "emb-test-value-0123456789abcdef"

    await bootstrap(
        sandbox,
        SANDBOX_ID,
        config,
        script="echo\n",
        gitlab_token=SecretStr(GITLAB_TOKEN),
        memory_ref=MEMORY_REF,
        memory_repo=MEMORY_REPO,
        embedding_key=SecretStr(embedding),
    )

    path = _script_path(sandbox)
    execs = [entry for entry in sandbox.journal if entry.method == "exec" and entry.cmd]
    assert execs[0].cmd == (
        f"bash {path} --claude-version 2.1.292 --openspec-version 1.14.3 "
        "--gitlab-url https://gitlab.com "
        f"--memory-ref {MEMORY_REF} --memory-repo {MEMORY_REPO} demo=https://gitlab.com/group/demo.git"
    )
    assert execs[0].env_keys == (
        "EMBEDDING_API_KEY",
        "GITLAB_TOKEN",
        "GIT_TERMINAL_PROMPT",
        "HARNESS_SANDBOX_BOOTSTRAP",
    )
    assert sandbox.received_env("EMBEDDING_API_KEY") == embedding
    assert all(embedding not in (entry.cmd or "") for entry in sandbox.journal)
    assert sandbox.files_containing(embedding) == []


class _TimeoutRecordingSandbox(FakeSandbox):
    """FakeSandbox, который запоминает таймаут каждой команды exec."""

    def __init__(self, sandbox_id: str) -> None:
        super().__init__(sandbox_id=sandbox_id)
        self.exec_timeouts: list[float] = []

    async def exec(
        self,
        sandbox_id: str,
        cmd: str,
        *,
        envs: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float = 60,
    ) -> ExecResult:
        self.exec_timeouts.append(timeout_s)
        return await super().exec(sandbox_id, cmd, envs=envs, cwd=cwd, timeout_s=timeout_s)


async def test_memory_bootstrap_uses_longer_timeout() -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = _TimeoutRecordingSandbox(sandbox_id=SANDBOX_ID)

    await bootstrap(
        sandbox,
        SANDBOX_ID,
        config,
        script="echo\n",
        gitlab_token=SecretStr(GITLAB_TOKEN),
        memory_ref=MEMORY_REF,
        memory_repo=MEMORY_REPO,
    )

    # Первая команда — bootstrap с длинным таймаутом; следом идёт короткий rm очистки скрипта.
    assert sandbox.exec_timeouts[0] == 1800


def test_script_does_not_embed_embedding_key_literal() -> None:
    # Допустимо только присваивание переменной оболочки ("$embedding_key"), литерала — нет.
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert re.findall(r'EMBEDDING_API_KEY=(?!["\']?\$)', text) == []


def _run_script(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Запуск скрипта с аргументами; при ошибке аргументов и --help установки не начинаются."""
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


ARGS_BASE = ("--claude-version", "2.1.292", "--openspec-version", "1.14.3")
VALID_PAIR = "demo=https://gitlab.com/group/demo.git"


@pytest.mark.parametrize("ref", ["v1.0.0", "09e5e63", "main", MEMORY_REF.upper()])
def test_script_rejects_malformed_memory_ref(ref: str) -> None:
    result = _run_script(*ARGS_BASE, "--memory-ref", ref, "--memory-repo", MEMORY_REPO, VALID_PAIR)

    assert result.returncode == 2
    assert "--memory-ref" in result.stderr


def test_script_rejects_malformed_memory_repo() -> None:
    result = _run_script(
        *ARGS_BASE, "--memory-ref", MEMORY_REF, "--memory-repo", "a/b/c", VALID_PAIR
    )

    assert result.returncode == 2
    assert "--memory-repo" in result.stderr


@pytest.mark.parametrize(
    "memory_args",
    [("--memory-ref", MEMORY_REF), ("--memory-repo", MEMORY_REPO)],
)
def test_script_requires_memory_ref_and_repo_together(memory_args: tuple[str, str]) -> None:
    result = _run_script(*ARGS_BASE, *memory_args, VALID_PAIR)

    assert result.returncode == 2
    assert "задаются вместе" in result.stderr


def test_script_rejects_removed_memory_version_flag() -> None:
    result = _run_script(*ARGS_BASE, "--memory-version", "1.2.3", VALID_PAIR)

    assert result.returncode == 2
    assert "неизвестный аргумент" in result.stderr


def test_script_help_exits_zero() -> None:
    result = _run_script("--help")

    assert result.returncode == 0
    assert "--memory-ref" in result.stdout
    assert "--memory-repo" in result.stdout


def test_script_unsets_secrets_before_any_install_step() -> None:
    """Ключи не попадают в env postinst apt и lifecycle-скриптов npm (ревью, пункт 1)."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    unset_pos = text.index("unset GITLAB_TOKEN EMBEDDING_API_KEY")
    for marker in ("\nensure_node\n", 'ensure_npm_package "@anthropic', "\n  ensure_acl\n"):
        assert unset_pos < text.index(marker), marker
    assert not re.search(r"\bexport\b", text)


def test_script_scopes_secret_assignments_to_memory_init_only() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Присваивание ключа embeddings — только в memory init; ключ GitLab в env git не присваивается.
    assignments = re.findall(r"\b(GITLAB_TOKEN|EMBEDDING_API_KEY)=", text)
    assert assignments == ["EMBEDDING_API_KEY"]
    assert 'EMBEDDING_API_KEY="$embedding_key" memory init --path "$dir"' in text
    assert "memory service" not in "".join(
        line for line in text.splitlines() if "EMBEDDING" in line
    )


def test_script_runs_argument_path_with_secrets_in_env() -> None:
    env = {
        **os.environ,
        "GITLAB_TOKEN": "glpat-test-env-0123",
        "EMBEDDING_API_KEY": "emb-test-env",
    }
    help_run = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--help"], capture_output=True, text=True, check=False, env=env
    )
    bad_run = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--memory-ref", "x"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert help_run.returncode == 0
    assert bad_run.returncode == 2
    assert "glpat-test-env" not in bad_run.stderr + help_run.stdout


def test_acl_install_is_independent_of_docker_branch() -> None:
    """setfacl нужен ensure-docker.sh и при уже стоящем Docker: acl ставится отдельно (пункт 6)."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    body = text[text.index("ensure_acl() {") : text.index("ensure_docker() {")]
    assert "apt_install acl" in body
    assert "ca-certificates curl acl" not in text
    assert text.index("\n  ensure_acl\n") < text.index("\n  ensure_docker\n")


def test_script_installs_memory_agent_from_github_pinned_commit() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'spec="github:${memory_repo}#${memory_ref}"' in text
    assert 'npm_global install -g "$spec"' in text
    assert "project-memory" not in text
    assert "ensure_npm_package project-memory" not in text
    assert "installed-ref" in text
    # Маркер пишется только после установки.
    assert text.index('npm_global install -g "$spec"') < text.index('mv "$marker.tmp" "$marker"')


def test_npm_global_and_root_writes_run_with_umask_022() -> None:
    """umask 077 скрипта через sudo дал бы root-файлам 0600: npm и apt работают в подшелле с 022."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    npm_body = text[text.index("npm_global() {") : text.index("# Ставит пакет")]
    root_body = text[text.index("root_umask() {") : text.index("apt_update() {")]
    assert "umask 022" in npm_body
    assert "umask 022" in root_body


@pytest.mark.parametrize(
    "kwargs",
    [{"memory_ref": MEMORY_REF}, {"memory_repo": MEMORY_REPO}],
)
async def test_bootstrap_rejects_memory_ref_without_repo(kwargs: dict[str, Any]) -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID)

    with pytest.raises(ValueError, match="задаются вместе"):
        await bootstrap(
            sandbox,
            SANDBOX_ID,
            config,
            script="echo\n",
            gitlab_token=SecretStr(GITLAB_TOKEN),
            **kwargs,
        )

    assert sandbox.journal == []


def _git_env_lines(text: str) -> list[str]:
    """Строки скрипта, где задаётся заголовок git (присваивание GIT_CONFIG_VALUE_0)."""
    return [line for line in text.splitlines() if "GIT_CONFIG_VALUE_0=" in line]


def test_script_has_no_askpass_and_removes_leftover_file() -> None:
    """Заголовок вместо askpass (D-52): askpass не создаётся, старый файл удаляется."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "GIT_ASKPASS" not in text
    assert "GITLAB_HOST" not in text
    askpass_lines = [
        line
        for line in text.splitlines()
        if "git-askpass" in line and not line.lstrip().startswith("#")
    ]
    assert askpass_lines == ['rm -f "$HARNESS_DIR/bin/git-askpass.sh"']


def test_script_sends_auth_header_only_on_clone_and_fetch() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert text.count("Authorization: Basic") == 1  # только в присваивании git_auth_header
    # Заголовок задаётся один раз в обёртке run_git_auth и только при непустом токене.
    assert text.count('GIT_CONFIG_KEY_0="http.${gitlab_url}.extraHeader"') == 1
    assert text.count('GIT_CONFIG_VALUE_0="$git_auth_header"') == 1
    assert text.count("GIT_CONFIG_COUNT=2") == 1
    assert text.count("GIT_CONFIG_VALUE_1=false") == 1
    assert "run_git_auth clone --quiet" in text
    assert 'run_git_auth -C "$dir" fetch' in text
    assert 'if [ -n "$git_auth_header" ]; then' in text
    # Заголовок не экспортируется и не пишется в файлы.
    assert not re.search(r"\bexport\b", text)
    assert '> "$HARNESS_DIR/bin/git' not in text


def test_script_builds_header_from_token_via_builtins_and_stdin() -> None:
    """Токен не попадает в argv: printf (builtin) и base64 получают его через конвейер и stdin."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "printf '%s' \"oauth2:$gitlab_token\" | base64 -w0" in text


def test_script_unsets_token_and_does_not_export_it() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "unset GITLAB_TOKEN EMBEDDING_API_KEY" in text
    assert "export GITLAB_TOKEN" not in text


@pytest.mark.parametrize(
    "url",
    ["https://gitlab.example.com", "https://gitlab.example.com:8443/", "https://host/some/path/"],
)
def test_script_accepts_valid_gitlab_url(url: str) -> None:
    result = _run_script(*ARGS_BASE, "--gitlab-url", url, "--help")

    assert result.returncode == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://gitlab.example.com",  # только https
        "https://user@gitlab.example.com",  # учётные данные
        "https://gitlab.example.com/a b",  # пробел
        "https://gitlab.example.com/?q=1",  # query
        "gitlab.example.com",  # без схемы
    ],
)
def test_script_rejects_malformed_gitlab_url(url: str) -> None:
    result = _run_script(*ARGS_BASE, "--gitlab-url", url, VALID_PAIR)

    assert result.returncode == 2
    assert "--gitlab-url" in result.stderr


def test_script_requires_gitlab_url_when_clones_are_given() -> None:
    result = _run_script(*ARGS_BASE, VALID_PAIR)

    assert result.returncode == 2
    assert "--gitlab-url" in result.stderr


def test_script_allows_anonymous_clones_without_token(tmp_path: Path) -> None:
    """Без токена клоны идут анонимно (публичные репозитории): ошибки токена нет, работает guard."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    result = _run_script(
        *ARGS_BASE, "--gitlab-url", "https://gitlab.example.com", VALID_PAIR, env=env
    )

    # Код 3 от guard: до проверки токена и до установок. Токен не требуется для клонов.
    assert result.returncode == 3
    assert "GITLAB_TOKEN" not in result.stderr
    assert 'GIT_TERMINAL_PROMPT=0 git "$@"' in SCRIPT_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("repo", ["../..", "./.", "-x/y", "x./y", "w1do/-agent"])
def test_script_rejects_repo_segments_that_are_not_names(repo: str) -> None:
    result = _run_script(*ARGS_BASE, "--memory-ref", MEMORY_REF, "--memory-repo", repo, VALID_PAIR)

    assert result.returncode == 2
    assert "--memory-repo" in result.stderr


def test_npm_home_is_created_private_before_npm_calls() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    body = text[text.index("npm_global() {") : text.index("local prefix")]
    assert 'mkdir -m 700 "$HOME/.npm"' in body
    assert 'chmod 700 "$HOME/.npm"' in body
    assert "root_umask sudo -n env DEBIAN_FRONTEND=noninteractive apt-get remove -y npm" in text


STUB_TOOLS = (
    "npm",
    "sudo",
    "apt-get",
    "dpkg",
    "git",
    "curl",
    "gpg",
    "systemctl",
    "docker",
    "memory",
)


def test_script_refuses_to_run_outside_sandbox_without_marker_variable(tmp_path: Path) -> None:
    """Без HARNESS_SANDBOX_BOOTSTRAP=1 скрипт выходит с кодом 3 до побочных эффектов (ревью)."""
    home = tmp_path / "home"
    home.mkdir()
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    marker_dir = tmp_path / "markers"
    marker_dir.mkdir()
    for tool in STUB_TOOLS:
        stub = stubs / tool
        stub.write_text(
            f'#!/usr/bin/env bash\ntouch "{marker_dir}/{tool}"\nexit 0\n', encoding="utf-8"
        )
        stub.chmod(0o755)
    env = {
        "PATH": f"{stubs}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(home),
        "GITLAB_TOKEN": "tok-test-guard-0123456789",
    }

    result = _run_script(
        *ARGS_BASE, "--gitlab-url", "https://gitlab.example.com", VALID_PAIR, env=env
    )

    assert result.returncode == 3
    assert "HARNESS_SANDBOX_BOOTSTRAP=1" in result.stderr
    assert list(marker_dir.iterdir()) == []
    assert list(home.iterdir()) == []


def test_script_guard_is_after_argument_validation(tmp_path: Path) -> None:
    """Ошибка аргументов по-прежнему даёт код 2, а не 3: проверка аргументов идёт раньше."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}

    result = _run_script(*ARGS_BASE, "--gitlab-url", "http://insecure.example", VALID_PAIR, env=env)

    assert result.returncode == 2


async def test_bootstrap_command_env_marks_sandbox_run() -> None:
    """services/sandboxes.bootstrap ставит HARNESS_SANDBOX_BOOTSTRAP=1: иначе скрипт не работает."""
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID)

    await bootstrap(
        sandbox,
        SANDBOX_ID,
        config,
        script="echo\n",
        gitlab_token=SecretStr(GITLAB_TOKEN),
    )

    assert sandbox.received_env("HARNESS_SANDBOX_BOOTSTRAP") == "1"


async def test_bootstrap_without_token_has_no_gitlab_env() -> None:
    """Публичные репозитории: токена нет, в env команды нет GITLAB_TOKEN (анонимные клоны, D-52)."""
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID)

    await bootstrap(sandbox, SANDBOX_ID, config, script="echo\n", gitlab_token=None)

    assert sandbox.received_env("GITLAB_TOKEN") is None
    assert "GITLAB_TOKEN" not in sandbox.journal[-1].env_keys
    assert sandbox.received_env("HARNESS_SANDBOX_BOOTSTRAP") == "1"


def test_apt_update_precedes_apt_install_in_every_function() -> None:
    """Образ песочницы может прийти с пустыми списками apt: update в функции раньше install."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Сегмент — от определения функции (любой отступ) до следующего определения.
    definition = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\(\) \{$", re.MULTILINE)
    starts = [m.start() for m in definition.finditer(text)] + [len(text)]
    checked = 0
    for begin, end in pairwise(starts):
        segment = text[begin:end]
        install = re.search(r"^\s*(?!apt_install\(\))(apt_install )", segment, re.MULTILINE)
        if install is None:
            continue
        checked += 1
        update = re.search(r"^\s*apt_update$", segment, re.MULTILINE)
        first_line = segment.splitlines()[0]
        ordered = update is not None and update.start() < install.start()
        assert ordered, f"apt_install без apt_update раньше в функции: {first_line}"
    assert checked >= 3  # ensure_node, ensure_acl, ensure_docker (и их ветки)


async def test_consecutive_bootstraps_use_different_script_paths() -> None:
    """Повторный bootstrap не пишет в тот же файл: fs.protected_regular=2 в sticky /tmp (D-52)."""
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID)

    for _ in range(2):
        await bootstrap(
            sandbox, SANDBOX_ID, config, script="echo ok\n", gitlab_token=SecretStr(GITLAB_TOKEN)
        )

    paths = _written_script_paths(sandbox)
    assert len(paths) == 2
    assert paths[0] != paths[1]
    assert all(SCRIPT_PATH_RE.fullmatch(p) for p in paths)
    assert all(p.startswith(BOOTSTRAP_SCRIPT_PREFIX) for p in paths)


async def test_script_is_removed_after_successful_bootstrap() -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID)

    await bootstrap(
        sandbox, SANDBOX_ID, config, script="echo ok\n", gitlab_token=SecretStr(GITLAB_TOKEN)
    )

    path = _script_path(sandbox)
    rm_cmds = [e.cmd for e in sandbox.journal if e.method == "exec" and e.cmd and "rm -f" in e.cmd]
    assert rm_cmds == [f"rm -f {path}"]


async def test_script_is_removed_when_bootstrap_command_fails() -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = _FailingBashSandbox(sandbox_id=SANDBOX_ID)

    with pytest.raises(SandboxUnavailable):
        await bootstrap(
            sandbox, SANDBOX_ID, config, script="echo ok\n", gitlab_token=SecretStr(GITLAB_TOKEN)
        )

    path = _script_path(sandbox)
    rm_cmds = [e.cmd for e in sandbox.journal if e.method == "exec" and e.cmd and "rm -f" in e.cmd]
    assert rm_cmds == [f"rm -f {path}"]


async def test_failed_script_cleanup_does_not_change_bootstrap_result() -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = _FailingRmSandbox(sandbox_id=SANDBOX_ID)

    result = await bootstrap(
        sandbox, SANDBOX_ID, config, script="echo ok\n", gitlab_token=SecretStr(GITLAB_TOKEN)
    )

    assert result.exit_code == 0
