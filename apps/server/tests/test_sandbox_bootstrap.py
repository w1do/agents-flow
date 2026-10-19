"""Подготовка песочницы через services/sandboxes.bootstrap на FakeSandbox (mvp-06, 2.3).

Без сети и без GitLab. Проверяются команда и её аргументы из конфига, передача токена только в env
и отсутствие значения токена в записанном скрипте и в файлах песочницы.
"""

import os
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
