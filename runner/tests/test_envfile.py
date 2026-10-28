import pytest

from runner.config import Config
from runner.errors import RunnerError


def write_config(path, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("OPENAI_API_KEY=file-key\nOPENAI_BASE_URL=https://file.example/v1\nAGENT_MODEL=file-model\n")
    path.chmod(mode)


def test_provider_loads_private_default_config_and_explicit_env_wins(tmp_path):
    path = tmp_path / ".config/agents-flow/runner.env"
    write_config(path)
    env = {"HOME": str(tmp_path), "AGENT_PROVIDER": "deepagents"}
    config = Config.from_env(env)
    assert (config.api_key, config.base_url, config.model) == (
        "file-key", "https://file.example/v1", "file-model")
    env.update(OPENAI_API_KEY="explicit-key", OPENAI_BASE_URL="https://explicit.example/v1",
               AGENT_MODEL="explicit-model")
    config = Config.from_env(env)
    assert config.api_key == "explicit-key"
    assert config.model == "explicit-model"
    assert config.base_url == "https://explicit.example/v1"


def test_wide_file_permissions_are_rejected(tmp_path):
    path = tmp_path / "runner.env"
    write_config(path, 0o640)
    with pytest.raises(RunnerError, match="permissions"):
        Config.from_env({"AGENT_PROVIDER": "deepagents",
                         "AGENT_FLOW_RUNNER_ENV_FILE": str(path)})


def test_env_file_rejects_unknown_or_duplicate_keys(tmp_path):
    path = tmp_path / "runner.env"
    path.write_text("OPENAI_API_KEY=one\nOPENAI_API_KEY=two\n")
    path.chmod(0o600)
    with pytest.raises(RunnerError, match="unique"):
        Config.from_env({"AGENT_PROVIDER": "deepagents",
                         "AGENT_FLOW_RUNNER_ENV_FILE": str(path)})


def test_env_file_values_are_redacted_with_base64(tmp_path, monkeypatch):
    import base64
    import io

    from runner.protocol import Events

    secret = "env-file-private-key-value"
    path = tmp_path / "runner.env"
    path.write_text(f"OPENAI_API_KEY={secret}\n")
    path.chmod(0o600)
    monkeypatch.setenv("AGENT_FLOW_RUNNER_ENV_FILE", str(path))
    Config.from_env()
    output = io.StringIO()
    Events(output).emit("progress", message=f"{secret} {base64.b64encode(secret.encode()).decode()}")
    assert secret not in output.getvalue()
    assert base64.b64encode(secret.encode()).decode() not in output.getvalue()


def test_invalid_env_file_still_allows_sanitized_failure_event(tmp_path, monkeypatch):
    import io
    import json

    from runner.cli import main

    path = tmp_path / "runner.env"
    write_config(path, 0o644)
    monkeypatch.setenv("AGENT_FLOW_RUNNER_ENV_FILE", str(path))
    output = io.StringIO()
    code = main([], stdin=io.StringIO("{}"), stdout=output)
    assert code == 1
    assert json.loads(output.getvalue())["type"] == "failure"
