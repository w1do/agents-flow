import io
import json
import sys
import types
from types import SimpleNamespace

from runner.config import Config
from runner.sdk import DeepAgentsAdapter, HIDDEN_TOOLS


def install_sdk(monkeypatch, invoke):
    registrations = {}
    deepagents = types.ModuleType("deepagents")
    deepagents.GeneralPurposeSubagentProfile = lambda **kwargs: SimpleNamespace(**kwargs)
    deepagents.HarnessProfile = lambda **kwargs: SimpleNamespace(**kwargs)
    deepagents.register_harness_profile = lambda name, profile: registrations.update(
        name=name, profile=profile)
    deepagents.create_deep_agent = lambda **kwargs: SimpleNamespace(invoke=lambda payload, **_kwargs: invoke(payload))
    langchain = types.ModuleType("langchain_openai")
    langchain.ChatOpenAI = lambda **kwargs: SimpleNamespace(config=kwargs)
    monkeypatch.setitem(sys.modules, "deepagents", deepagents)
    monkeypatch.setitem(sys.modules, "langchain_openai", langchain)
    return registrations


def config():
    return Config("deepagents", "https://example.invalid/v1", "offline-test-key", "offline-model")


def test_sdk_excludes_direct_tools_and_subagents(monkeypatch):
    registrations = install_sdk(
        monkeypatch, lambda _input: {"messages": [SimpleNamespace(content='{"action":"finish"}')]} )
    adapter = DeepAgentsAdapter(config())
    profile = registrations["profile"]
    assert registrations["name"] == "openai"
    assert set(profile.excluded_tools) == HIDDEN_TOOLS
    assert profile.general_purpose_subagent.enabled is False
    assert adapter.complete([]) == '{"action":"finish"}'


def test_real_sdk_tool_inventory_is_fully_blocked():
    adapter = DeepAgentsAdapter(config())
    assert adapter.sdk_tool_names <= HIDDEN_TOOLS
    assert "delete" in adapter.sdk_tool_names
    assert not adapter.agent.nodes["tools"].bound._tools_by_name


def test_sdk_request_errors_are_sanitized(monkeypatch):
    def fail(_input):
        raise RuntimeError("provider internals with secret")

    install_sdk(monkeypatch, fail)
    adapter = DeepAgentsAdapter(config())
    try:
        adapter.complete([])
    except Exception as error:
        assert str(error) == "Deep Agents model request failed"
    else:
        raise AssertionError("SDK request error was not raised")


def test_sdk_failure_produces_terminal_failure_event(monkeypatch, task_input):
    install_sdk(monkeypatch, lambda _input: (_ for _ in ()).throw(RuntimeError("private detail")))
    monkeypatch.setattr("runner.cli.Config.from_env", lambda: config())
    task_input.update(stage="implementation", read_only=False)
    output = io.StringIO()
    from runner.cli import main

    code = main([], stdin=io.StringIO(json.dumps(task_input)), stdout=output)
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert code == 1
    assert events[-1] == {"type": "failure", "message": "Deep Agents model request failed",
                          "checkpoint": None}
    assert "private detail" not in output.getvalue()
