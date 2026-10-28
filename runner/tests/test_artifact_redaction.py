import io
import json
import base64
from urllib.parse import quote
from types import SimpleNamespace

from runner.deepagents import run
from runner.protocol import Events, parse_json
from runner.workspace import Workspace
from runner.redaction import redact
from runner.config import Config


class Actions:
    def __init__(self, actions):
        self.actions = iter(actions)

    def complete(self, _messages):
        return json.dumps(next(self.actions))


def test_env_file_secret_is_masked_in_artifact_and_events(tmp_path, monkeypatch):
    secret = "artifact-secret-from-env-file"
    env_file = tmp_path / "runner.env"
    env_file.write_text(f"OPENAI_API_KEY={secret}\n")
    env_file.chmod(0o600)
    monkeypatch.setenv("AGENT_FLOW_RUNNER_ENV_FILE", str(env_file))
    Config.from_env()
    worktree = tmp_path / "work"
    worktree.mkdir()
    workspace = Workspace(str(worktree))
    request = SimpleNamespace(
        stage="implementation", workspace=workspace,
        data={"task": {}, "stage": "implementation", "read_only": False,
              "skills": [], "result_data": None},
    )
    actions = Actions([
        {"action": "write_file", "path": f"artifact-{secret}.txt", "content": f"value={secret}"},
        {"action": "finish", "result_summary": "Completed"},
    ])
    output = io.StringIO()
    run(request, Events(output), SimpleNamespace(provider="stub"), adapter=actions)
    workspace.close()
    events = [parse_json(line) for line in output.getvalue().splitlines()]
    artifacts = list(worktree.iterdir())
    assert len(artifacts) == 1
    assert secret not in artifacts[0].name
    assert secret not in artifacts[0].read_text()
    assert "[REDACTED]" in artifacts[0].name
    assert "[REDACTED]" in artifacts[0].read_text()
    assert all(secret not in line for line in output.getvalue().splitlines())
    assert any(event.get("warning") == "artifact_redacted" for event in events)


def test_secret_encodings_and_numeric_payload_are_masked(tmp_path, monkeypatch):
    secret = "  731983574620  "
    env_file = tmp_path / "runner.env"
    env_file.write_text(f'OPENAI_API_KEY={secret}\n')
    env_file.chmod(0o600)
    env = {"AGENT_FLOW_RUNNER_ENV_FILE": str(env_file), "AGENT_PROVIDER": "stub"}
    Config.from_env(env)
    stripped = secret.strip()
    values = [stripped, f'"{stripped}"', f"'{stripped}'", quote(stripped, safe=""),
              base64.b64encode(stripped.encode()).decode(),
              base64.urlsafe_b64encode(stripped.encode()).decode().rstrip("=")]
    result = redact({"payload": values + [int(stripped), float(stripped)],
                     "name": quote(stripped, safe="")})
    rendered = json.dumps(result)
    for value in values + [stripped]:
        assert value not in rendered
    assert result["payload"][-2:] == ["[REDACTED]", "[REDACTED]"]


def test_redaction_snapshot_keeps_rotated_secrets_and_adds_new(tmp_path):
    env_file = tmp_path / "runner.env"
    env_file.write_text("OPENAI_API_KEY=old-secret\n")
    env_file.chmod(0o600)
    env = {"AGENT_FLOW_RUNNER_ENV_FILE": str(env_file), "AGENT_PROVIDER": "stub"}
    Config.from_env(env)
    env_file.write_text("OPENAI_API_KEY=new-secret\n")
    Config.from_env(env)
    result = json.dumps(redact(["old-secret", "new-secret"]))
    assert "old-secret" not in result
    assert "new-secret" not in result


def test_model_response_history_is_redacted_before_next_provider_call(tmp_path, monkeypatch):
    secret = "context-secret-55881234"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    Config.from_env()
    worktree = tmp_path / "work"
    worktree.mkdir()
    workspace = Workspace(str(worktree))
    request = SimpleNamespace(stage="implementation", workspace=workspace,
                              data={"task": {}, "stage": "implementation", "read_only": False,
                                    "skills": [], "result_data": None})

    class InspectHistory:
        def __init__(self):
            self.calls = 0

        def complete(self, messages):
            self.calls += 1
            if self.calls == 1:
                return json.dumps({"action": "list_files", "path": ".", "private": secret})
            assistant = [m["content"] for m in messages if m["role"] == "assistant"]
            assert secret not in "".join(assistant)
            return json.dumps({"action": "finish", "result_summary": "Done"})

    output = io.StringIO()
    run(request, Events(output), SimpleNamespace(provider="stub"), adapter=InspectHistory())
    workspace.close()
