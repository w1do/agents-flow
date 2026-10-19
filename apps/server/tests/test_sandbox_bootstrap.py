"""Подготовка песочницы через services/sandboxes.bootstrap на FakeSandbox (mvp-06, 2.3).

Без сети и без GitLab. Проверяются команда и её аргументы из конфига, передача токена только в env
и отсутствие значения токена в записанном скрипте и в файлах песочницы.
"""

import os
import re
import subprocess
from pathlib import Path

from harness_server.adapters.novita import ExecResult, FakeSandbox
from harness_server.config import load_config
from harness_server.services.sandboxes import BOOTSTRAP_SCRIPT_PATH, bootstrap
from pydantic import SecretStr

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_CONFIG = REPO_ROOT / "config" / "harness.example.yaml"
SCRIPT_PATH = REPO_ROOT / "deploy" / "sandbox" / "bootstrap.sh"
SANDBOX_ID = "sbx-test-1"
# Тестовое значение в формате токена GitLab; настоящий токен здесь не используется.
GITLAB_TOKEN = "glpat-test-token-0123456789abcdef"

EXPECTED_COMMAND = (
    f"bash {BOOTSTRAP_SCRIPT_PATH} --claude-version 2.1.292 --openspec-version 1.14.3 "
    "demo=https://gitlab.com/group/demo.git"
)


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
    # Скрипт записан по абсолютному пути: в журнале есть запись write_file с этим путём.
    assert [e.cmd for e in sandbox.journal if e.method == "write_file"] == [BOOTSTRAP_SCRIPT_PATH]
    assert sandbox.files_containing("echo ok") == [BOOTSTRAP_SCRIPT_PATH]
    execs = [entry for entry in sandbox.journal if entry.method == "exec"]
    assert [entry.cmd for entry in execs] == [EXPECTED_COMMAND]
    assert execs[0].env_keys == ("GITLAB_TOKEN", "GIT_TERMINAL_PROMPT")


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
    assert [entry.method for entry in sandbox.journal] == ["connect", "write_file", "exec"]


def test_repo_bootstrap_script_is_executable_and_has_no_secret_values() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert os.access(SCRIPT_PATH, os.X_OK)
    assert GITLAB_TOKEN not in text
    # Шаблоны известных токенов: в скрипте допустима только ссылка на переменную, не значение.
    for prefix in ("glpat-", "sk-ant-", "nk-"):
        assert prefix not in text


async def test_memory_version_goes_to_script_args_and_key_only_to_env() -> None:
    config = load_config(EXAMPLE_CONFIG)
    sandbox = FakeSandbox(sandbox_id=SANDBOX_ID)
    embedding = "emb-test-value-0123456789abcdef"

    await bootstrap(
        sandbox,
        SANDBOX_ID,
        config,
        script="echo\n",
        gitlab_token=SecretStr(GITLAB_TOKEN),
        memory_version="1.2.3",
        embedding_key=SecretStr(embedding),
    )

    execs = [entry for entry in sandbox.journal if entry.method == "exec"]
    assert execs[0].cmd == (
        f"bash {BOOTSTRAP_SCRIPT_PATH} --claude-version 2.1.292 --openspec-version 1.14.3 "
        "--memory-version 1.2.3 demo=https://gitlab.com/group/demo.git"
    )
    assert execs[0].env_keys == ("EMBEDDING_API_KEY", "GITLAB_TOKEN", "GIT_TERMINAL_PROMPT")
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
        memory_version="1.2.3",
    )

    assert sandbox.exec_timeouts == [1800]


def test_script_does_not_embed_embedding_key_literal() -> None:
    # Допустимо только присваивание переменной оболочки ("$embedding_key"), литерала — нет.
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert re.findall(r'EMBEDDING_API_KEY=(?!["\']?\$)', text) == []


def test_script_rejects_malformed_memory_version() -> None:
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--claude-version",
            "2.1.292",
            "--openspec-version",
            "1.14.3",
            "--memory-version",
            "1.2",
            "demo=https://gitlab.com/group/demo.git",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--memory-version" in result.stderr


def test_script_help_exits_zero() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--help"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    assert "--memory-version" in result.stdout


def test_script_unsets_secrets_before_any_install_step() -> None:
    """Ключи не попадают в env postinst apt и lifecycle-скриптов npm (ревью, пункт 1)."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    unset_pos = text.index("unset GITLAB_TOKEN EMBEDDING_API_KEY")
    for marker in ("\nensure_node\n", 'ensure_npm_package "@anthropic', "\n  ensure_acl\n"):
        assert unset_pos < text.index(marker), marker
    assert not re.search(r"\bexport\b", text)


def test_script_scopes_secret_assignments_to_git_and_memory_init_only() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    # GITLAB_TOKEN — ровно в двух git-командах, EMBEDDING_API_KEY — только в memory init.
    assignments = re.findall(r"\b(GITLAB_TOKEN|EMBEDDING_API_KEY)=", text)
    assert sorted(assignments) == ["EMBEDDING_API_KEY", "GITLAB_TOKEN", "GITLAB_TOKEN"]
    git_lines = [line for line in text.splitlines() if 'GITLAB_TOKEN="$gitlab_token"' in line]
    assert len(git_lines) == 2
    assert all("GIT_ASKPASS" in line for line in git_lines)
    assert 'EMBEDDING_API_KEY="$embedding_key" memory init --path "$dir"' in text
    # memory service up и прочие команды ключ не получают.
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
        ["bash", str(SCRIPT_PATH), "--memory-version", "x"],
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
