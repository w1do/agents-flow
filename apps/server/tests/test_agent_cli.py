from pathlib import Path

import pytest
from harness_server import agent_cli
from harness_server.agent_cli import app
from harness_server.services import machine
from harness_server.services.machine import MachineError, require_non_root
from typer.testing import CliRunner


def test_agent_help_names_harness() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "agents-flow" in result.output


def _config(path: Path) -> None:
    path.write_text(
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    repo: {provider: github, project: owner/demo}\n"
        "sandbox: {provider_id: local}\n"
    )


def test_agent_init_unknown_project_is_code_two_without_server_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "harness.yaml"
    _config(config)
    monkeypatch.setenv("HARNESS_CONFIG", str(config))

    result = CliRunner().invoke(app, ["init", "unknown"])

    assert result.exit_code == 2
    assert "неизвестный проект" in result.output


def test_agent_init_missing_config_never_echoes_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "synthetic-vault-token-must-not-appear"
    monkeypatch.delenv("HARNESS_CONFIG", raising=False)
    monkeypatch.setenv("VAULT_MCP_TOKEN", token)

    result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 1
    assert token not in result.output
    assert "HARNESS_CONFIG" in result.output


def test_agent_init_root_uses_real_root_helper_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "harness.yaml"
    _config(config)
    monkeypatch.setenv("HARNESS_CONFIG", str(config))
    monkeypatch.setattr(machine, "require_non_root", lambda: require_non_root(uid=0))

    result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 1
    assert "отдельный пользователь" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (MachineError(1, "нужен отдельный пользователь без root"), 1),
        (MachineError(1, "vault"), 1),
        (MachineError(3, "нет git"), 3),
    ],
)
def test_agent_init_maps_service_failures_without_db_or_telegram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: MachineError,
    code: int,
) -> None:
    config = tmp_path / "harness.yaml"
    _config(config)
    monkeypatch.setenv("HARNESS_CONFIG", str(config))

    async def fail(*_: object) -> None:
        raise error

    monkeypatch.setattr(agent_cli, "init_project", fail)
    result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == code
    assert str(error) in result.output


def test_agent_init_success_uses_minimal_agent_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "harness.yaml"
    _config(config)
    monkeypatch.setenv("HARNESS_CONFIG", str(config))
    calls: list[str] = []

    async def success(_config: object, project: str, _vault: object) -> None:
        calls.append(project)

    monkeypatch.setattr(agent_cli, "init_project", success)
    result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 0
    assert calls == ["demo"]
