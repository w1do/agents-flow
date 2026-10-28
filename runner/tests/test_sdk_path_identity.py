import io
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from runner.config import Config
from runner.deepagents import run
from runner.errors import RunnerError
from runner.model_paths import PathIdentity
from runner.protocol import Events
from runner.workspace import Workspace


@pytest.mark.parametrize("reverse", [False, True])
def test_real_sdk_keeps_original_path_identity_outside_redacted_history(tmp_path, monkeypatch, reverse):
    secret = "sdk-path-identity-credential-79841"
    config = Config.from_env({"SERVICE_KEY": secret, "AGENT_PROVIDER": "deepagents",
                              "OPENAI_API_KEY": "offline-sdk-identity-key", "AGENT_MODEL": "offline"})
    paths = ["[REDACTED].txt", f"{secret}.txt"]
    if reverse:
        paths.reverse()
    actions = iter([
        {"action": "write_file", "path": paths[0], "content": "first"},
        {"action": "write_file", "path": paths[1], "content": "second"},
        {"action": "write_file", "path": paths[0], "content": "updated first"},
        {"action": "finish", "result_summary": "Done"},
    ])

    def generate(_self, messages, **_kwargs):
        assert secret not in json.dumps([message.model_dump() for message in messages])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=json.dumps(next(actions))))])

    monkeypatch.setattr(ChatOpenAI, "_generate", generate)
    workspace = Workspace(str(tmp_path))
    output = io.StringIO()
    try:
        run(SimpleNamespace(stage="implementation", workspace=workspace, data={}), Events(output), config)
        assert sorted(p.read_text() for p in tmp_path.iterdir()) == ["second", "updated first"]
        assert secret not in output.getvalue() + str(list(tmp_path.iterdir()))
    finally:
        workspace.close()


def test_sdk_missing_path_identity_fails_closed():
    with pytest.raises(RunnerError, match="identity unavailable"):
        PathIdentity().reply('{"action":"write_file","path":"[REDACTED]","content":"new"}')


def test_sdk_preserves_forbidden_original_path_until_validation(tmp_path, monkeypatch):
    import runner.secrets as secrets

    monkeypatch.setattr(secrets, "_active", secrets.SecretSnapshot())
    config = Config.from_env({"SERVICE_KEY": ".env", "AGENT_PROVIDER": "deepagents",
                              "OPENAI_API_KEY": "offline-sdk-forbidden-key", "AGENT_MODEL": "offline"})

    def generate(_self, messages, **_kwargs):
        content = json.dumps({"action": "write_file", "path": ".env.local", "content": "forbidden"})
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    monkeypatch.setattr(ChatOpenAI, "_generate", generate)
    workspace = Workspace(str(tmp_path))
    try:
        with pytest.raises(RunnerError, match="forbidden metadata"):
            run(SimpleNamespace(stage="implementation", workspace=workspace, data={}),
                Events(io.StringIO()), config)
        assert not list(tmp_path.iterdir())
    finally:
        workspace.close()
