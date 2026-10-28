import io
import json

import pytest

from runner.config import Config
from runner.deepagents import run
from runner.errors import RunnerError
from runner.protocol import Events, Request


def environment(**overrides):
    return {"AGENT_PROVIDER": "deepagents", "OPENAI_BASE_URL": "https://compatible.example/v1/",
            "OPENAI_API_KEY": "offline-config-key", "AGENT_MODEL": "configured-model", **overrides}


def test_environment_configuration_is_network_free_and_hides_key():
    config = Config.from_env(environment())
    assert config.provider == "deepagents"
    assert config.base_url == "https://compatible.example/v1"
    assert config.model == "configured-model"
    assert config.api_key == "offline-config-key"
    assert config.api_key not in repr(config)
    assert config.base_url not in repr(config)


def test_openai_model_takes_precedence_and_default_endpoint():
    env = environment(OPENAI_MODEL="openai-model")
    del env["OPENAI_BASE_URL"]
    config = Config.from_env(env)
    assert config.model == "openai-model"
    assert config.base_url == "https://api.openai.com/v1"


def test_from_process_environment(monkeypatch):
    for name, value in environment().items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert Config.from_env().model == "configured-model"


@pytest.mark.parametrize("overrides", [
    {"OPENAI_API_KEY": ""}, {"OPENAI_API_KEY": "bad\nkey"},
    {"AGENT_MODEL": ""}, {"OPENAI_BASE_URL": "file:///tmp/model"},
    {"OPENAI_BASE_URL": "https://user:private-key@model.example/v1"},
    {"OPENAI_BASE_URL": "https://model.example/v1?api_key=private-key"},
    {"OPENAI_BASE_URL": "https://model.example:wrong/v1"},
    {"OPENAI_BASE_URL": "https://model.example:0/v1"}, {"AGENT_PROVIDER": "unknown"},
])
def test_invalid_configuration_is_safe(overrides):
    with pytest.raises(RunnerError) as failure:
        Config.from_env(environment(**overrides))
    assert "private-key" not in str(failure.value)


def test_stub_needs_no_api_config_or_dependencies():
    assert Config.from_env({}).provider == "stub"
    assert Config.from_env({"AGENT_PROVIDER": "stub", "OPENAI_BASE_URL": "invalid"}).provider == "stub"
    assert Config.from_env(environment(AGENT_PROVIDER="openai-compatible")).provider == "openai-compatible"


class FakeAdapter:
    def __init__(self, *actions):
        self.actions = iter(actions)
        self.messages = []

    def complete(self, messages):
        self.messages.append(json.loads(messages[1]["content"]))
        return json.dumps(next(self.actions))


def execute(task_input, adapter):
    request = Request.read(io.StringIO(json.dumps(task_input)))
    output = io.StringIO()
    run(request, Events(output), Config.from_env(environment()), adapter=adapter)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_adapter_receives_skill_snapshot_feedback_and_checkpoint(task_input):
    task_input.update(plan_text="Approved", feedback="Use smaller change", checkpoint={"cursor": "saved"},
                      skills=[{"category": "development", "content": "Inline instructions"}])
    adapter = FakeAdapter({"action": "finish", "plan_text": "A safe plan"})
    assert execute(task_input, adapter) == [{"type": "plan", "plan_text": "A safe plan"}]
    context = adapter.messages[0]
    assert context["skills"] == task_input["skills"]
    assert context["feedback"] == "Use smaller change"
    assert context["checkpoint"] == {"cursor": "saved"}


def test_deep_agent_modifies_real_worktree_file(task_input, tmp_path):
    task_input.update(stage="implementation", read_only=False)
    (tmp_path / "source.txt").write_text("before")
    adapter = FakeAdapter(
        {"action": "read_file", "path": "source.txt"},
        {"action": "write_file", "path": "source.txt", "content": "after"},
        {"action": "finish", "result_summary": "Updated source"})
    events = execute(task_input, adapter)
    assert (tmp_path / "source.txt").read_text() == "after"
    assert events[-1] == {"type": "result", "result_summary": "Updated source",
                          "result_data": {"changed_paths": ["source.txt"]}}


@pytest.mark.parametrize("path", ["../escape.txt", "/etc/passwd", ".env", ".env.local", "workflow/.agent-token"])
def test_model_cannot_write_forbidden_path(task_input, path):
    task_input.update(stage="implementation", read_only=False)
    with pytest.raises(RunnerError):
        execute(task_input, FakeAdapter({"action": "write_file", "path": path, "content": "bad"}))


def test_model_cannot_write_in_planning(task_input, tmp_path):
    with pytest.raises(RunnerError, match="read-only"):
        execute(task_input, FakeAdapter({"action": "write_file", "path": "bad.txt", "content": "bad"}))
    assert not (tmp_path / "bad.txt").exists()


def test_resuming_implementation_reports_previous_changes(task_input, tmp_path):
    (tmp_path / "changed.txt").write_text("saved")
    task_input.update(stage="implementation", read_only=False, checkpoint={
        "stage": "implementation", "changed_paths": ["changed.txt"]})
    events = execute(task_input, FakeAdapter({"action": "finish", "result_summary": "Resumed"}))
    assert events[-1]["result_data"]["changed_paths"] == ["changed.txt"]
