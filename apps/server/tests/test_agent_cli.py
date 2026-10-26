"""agent init через CliRunner: настройки с сервера (respx), локальный конфиг 0600, отказы (D-65)."""

import os
import stat
from pathlib import Path

import httpx
import pytest
import respx
from harness_server import agent_cli
from harness_server.agent_cli import app
from harness_server.services.machine import MachineError, require_non_root
from typer.testing import CliRunner

SERVER = "https://harness.example.com"
TOKEN = "operator-token-0123456789abcdef0123456789"
SETTINGS: dict[str, object] = {
    "id": "demo",
    "name": "Demo",
    "voice_aliases": [],
    "repo": {
        "provider": "github",
        "base_url": "https://github.com",
        "project": "owner/demo",
        "access_ref": "vault:demo/github/main",
    },
    "default_branch": "main",
    "test_command": None,
    "agent": "claude-code",
    "agent_max_turns": 50,
}


@pytest.fixture
def agent_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """ENV агента: конфиг только с песочницей, адрес сервера и токен оператора; HOME — tmp."""
    config = tmp_path / "harness.yaml"
    config.write_text("sandbox: {provider_id: local}\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_CONFIG", str(config))
    monkeypatch.setenv("HARNESS_PUBLIC_URL", SERVER)
    monkeypatch.setenv("HARNESS_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("VAULT_MCP_URL", raising=False)
    monkeypatch.delenv("VAULT_MCP_TOKEN", raising=False)
    return home


def _allow_init(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Подготовка клона и маркера не выполняется: проверяем только запрос и локальный конфиг."""
    calls: list[str] = []

    async def success(_config: object, project: object, _vault: object) -> None:
        calls.append(str(getattr(project, "id", project)))

    monkeypatch.setattr(agent_cli, "init_project", success)
    monkeypatch.setattr(agent_cli, "require_non_root", lambda: None)
    return calls


def test_agent_help_names_harness() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "agents-flow" in result.output


def test_agent_init_success_writes_local_config_0600(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _allow_init(monkeypatch)
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{SERVER}/api/projects/demo/settings").mock(
            return_value=httpx.Response(200, json=SETTINGS)
        )
        result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 0, result.output
    assert calls == ["demo"]
    # Токен уходит только в заголовке Authorization.
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    local = agent_env / ".harness" / "projects" / "demo.yaml"
    assert stat.S_IMODE(os.stat(local).st_mode) == 0o600
    text = local.read_text(encoding="utf-8")
    assert "НЕ РЕДАКТИРОВАТЬ" in text
    assert "vault:demo/github/main" in text
    assert TOKEN not in text


def test_agent_init_rewrites_existing_config_with_0600(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_init(monkeypatch)
    local = agent_env / ".harness" / "projects" / "demo.yaml"
    local.parent.mkdir(parents=True, mode=0o700)
    local.write_text("старое содержимое\n", encoding="utf-8")
    os.chmod(local, 0o644)
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{SERVER}/api/projects/demo/settings").mock(
            return_value=httpx.Response(200, json=SETTINGS)
        )
        result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 0, result.output
    assert stat.S_IMODE(os.stat(local).st_mode) == 0o600
    assert "старое содержимое" not in local.read_text(encoding="utf-8")


def test_agent_init_without_server_is_clear_error(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_init(monkeypatch)
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{SERVER}/api/projects/demo/settings").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 1
    assert "сервер недоступен" in result.output
    assert "HARNESS_PUBLIC_URL" in result.output
    assert not (agent_env / ".harness" / "projects" / "demo.yaml").exists()


def test_agent_init_disabled_project_is_refused(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _allow_init(monkeypatch)
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{SERVER}/api/projects/demo/settings").mock(
            return_value=httpx.Response(409, json={"detail": "project_disabled"})
        )
        result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 1
    assert "отключён" in result.output
    assert calls == []
    assert not (agent_env / ".harness" / "projects" / "demo.yaml").exists()


def test_agent_init_unknown_project_is_code_two(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_init(monkeypatch)
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{SERVER}/api/projects/demo/settings").mock(
            return_value=httpx.Response(404, json={"detail": "not_found"})
        )
        result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 2
    assert "не найден" in result.output


def test_agent_init_rejected_token_does_not_echo_token(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_init(monkeypatch)
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{SERVER}/api/projects/demo/settings").mock(
            return_value=httpx.Response(401, json={"detail": "unauthorized"})
        )
        result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 1
    assert "HARNESS_ADMIN_TOKEN" in result.output
    assert TOKEN not in result.output


def test_agent_init_plain_http_to_remote_host_is_refused(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_init(monkeypatch)
    monkeypatch.setenv("HARNESS_PUBLIC_URL", "http://harness.example.com")

    result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 1
    assert "https" in result.output


def test_agent_init_rejects_invalid_project_id_before_network(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_init(monkeypatch)
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__regex=r".*").mock(return_value=httpx.Response(200))
        result = CliRunner().invoke(app, ["init", "../etc"])

    assert result.exit_code == 1
    assert not route.called


def test_agent_init_missing_server_env_names_variables(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_ADMIN_TOKEN")

    result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 1
    assert "HARNESS_ADMIN_TOKEN" in result.output
    assert TOKEN not in result.output


def test_agent_init_missing_config_never_echoes_secret_env(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "synthetic-vault-token-must-not-appear"
    monkeypatch.delenv("HARNESS_CONFIG", raising=False)
    monkeypatch.setenv("VAULT_MCP_TOKEN", token)

    result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 1
    assert token not in result.output
    assert "HARNESS_CONFIG" in result.output


def test_agent_init_root_uses_real_root_helper_without_traceback(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_cli, "require_non_root", lambda: require_non_root(uid=0))

    result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == 1
    assert "отдельный пользователь" in result.output
    assert "Traceback" not in result.output
    assert not (agent_env / ".harness").exists()


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (MachineError(1, "нужен отдельный пользователь без root"), 1),
        (MachineError(1, "vault"), 1),
        (MachineError(3, "нет git"), 3),
    ],
)
def test_agent_init_maps_service_failures_without_db_or_telegram(
    agent_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: MachineError,
    code: int,
) -> None:
    monkeypatch.setattr(agent_cli, "require_non_root", lambda: None)

    async def fail(*_: object) -> None:
        raise error

    monkeypatch.setattr(agent_cli, "init_project", fail)
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{SERVER}/api/projects/demo/settings").mock(
            return_value=httpx.Response(200, json=SETTINGS)
        )
        result = CliRunner().invoke(app, ["init", "demo"])

    assert result.exit_code == code
    assert str(error) in result.output
