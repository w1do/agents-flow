import io
import json
import re
from types import SimpleNamespace

import pytest

from runner.config import Config
from runner.deepagents import run
from runner.protocol import Events, parse_json
from runner.workspace import Workspace
from test_artifact_redaction import Actions


@pytest.mark.parametrize("sdk", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_secret_spanning_components_keeps_allocated_files(tmp_path, monkeypatch, sdk, reverse):
    secret = "review-synthetic-credential/part-79451"
    config = Config.from_env({"SERVICE_KEY": secret, "AGENT_PROVIDER": "deepagents",
                              "OPENAI_API_KEY": "offline-regression-key", "AGENT_MODEL": "offline"})
    paths = ["[REDACTED].txt", f"{secret}.txt"]
    if reverse:
        paths.reverse()
    actions = Actions([
        {"action": "write_file", "path": paths[0], "content": "first"},
        {"action": "write_file", "path": paths[1], "content": "second"},
        {"action": "finish", "result_summary": "Done"},
    ])
    if sdk:
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langchain_openai import ChatOpenAI

        def generate(_self, messages, **_kwargs):
            assert secret not in json.dumps([m.model_dump() for m in messages])
            reply = AIMessage(content=actions.complete(messages))
            return ChatResult(generations=[ChatGeneration(message=reply)])

        monkeypatch.setattr(ChatOpenAI, "_generate", generate)
    workspace = Workspace(str(tmp_path))
    output = io.StringIO()
    try:
        request = SimpleNamespace(stage="implementation", workspace=workspace, data={})
        run(request, Events(output), config, adapter=None if sdk else actions)
        files = [p for p in tmp_path.rglob("*") if p.is_file()]
        assert sorted(p.read_text() for p in files) == ["first", "second"]
        names = {p.name for p in files}
        assert "[REDACTED].txt" in names
        assert len(names) == 2
        assert all(re.fullmatch(r"\[REDACTED\]\.txt\.[0-9a-f]{24}", p)
                   for p in names if p != "[REDACTED].txt")
        events = [parse_json(line) for line in output.getvalue().splitlines()]
        assert len(events[-1]["result_data"]["changed_paths"]) == 2
        assert secret not in output.getvalue() + str(files)
    finally:
        workspace.close()


@pytest.mark.parametrize("nested", [False, True])
def test_canonical_read_owns_name_even_when_raw_write_has_binding(tmp_path, nested):
    secret = "canonical-owner-credential-48261"
    config = Config.from_env({"SERVICE_KEY": secret})
    suffix = "/file" if nested else ""
    outputs = []

    class InspectReads(Actions):
        def complete(self, messages):
            if len(messages) > 2 and parse_json(messages[-2]["content"])["action"] == "read_file":
                outputs.append(parse_json(messages[-1]["content"])["output"])
            if len(messages) == 8:
                path = parse_json(messages[-4]["content"])["path"]
                return json.dumps({"action": "read_file", "path": path})
            return super().complete(messages)

    workspace = Workspace(str(tmp_path))
    try:
        run(SimpleNamespace(stage="implementation", workspace=workspace, data={}),
            Events(io.StringIO()), config, adapter=InspectReads([
                {"action": "write_file", "path": f"{secret}.txt{suffix}", "content": "first"},
                {"action": "write_file", "path": f"[REDACTED].txt{suffix}", "content": "second"},
                {"action": "read_file", "path": f"[REDACTED].txt{suffix}"},
                {"action": "finish", "result_summary": "Done"},
            ]))
        assert outputs == ["first", "second"]
    finally:
        workspace.close()
