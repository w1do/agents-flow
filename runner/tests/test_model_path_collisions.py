import io
import json
from types import SimpleNamespace

import pytest

from runner.config import Config
from runner.deepagents import run
from runner.protocol import Events, parse_json
from runner.workspace import Workspace
from test_artifact_redaction import Actions


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_model_collision_keeps_distinct_files_and_repeated_writes(tmp_path, reverse, nested):
    secret = "model-path-collision-credential-99519"
    config = Config.from_env({"SERVICE_KEY": secret})
    paths = ["[REDACTED].txt", f"{secret}.txt"]
    if nested:
        paths = [p + "/file" for p in paths]
    if reverse:
        paths.reverse()
    actions = Actions([
        {"action": "write_file", "path": paths[0], "content": "first"},
        {"action": "write_file", "path": paths[1], "content": "second"},
        {"action": "write_file", "path": paths[0], "content": "updated first"},
        {"action": "read_file", "path": paths[1]},
        {"action": "finish", "result_summary": "Done"},
    ])
    workspace = Workspace(str(tmp_path))
    request = SimpleNamespace(stage="implementation", workspace=workspace, data={})
    output = io.StringIO()
    try:
        run(request, Events(output), config, adapter=actions)
    finally:
        workspace.close()
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert sorted(p.read_text() for p in files) == ["second", "updated first"]
    assert secret not in str(files) + output.getvalue()
    events = [parse_json(line) for line in output.getvalue().splitlines()]
    assert len(events[-1]["result_data"]["changed_paths"]) == 2


def test_model_sanitized_name_never_overwrites_preexisting_file(tmp_path):
    secret = "model-existing-collision-credential-79451"
    config = Config.from_env({"SERVICE_KEY": secret})
    (tmp_path / "[REDACTED].txt").write_text("existing")
    workspace = Workspace(str(tmp_path))
    request = SimpleNamespace(stage="implementation", workspace=workspace, data={})
    try:
        run(request, Events(io.StringIO()), config, adapter=Actions([
            {"action": "write_file", "path": f"{secret}.txt", "content": "new"},
            {"action": "finish", "result_summary": "Done"},
        ]))
        assert (tmp_path / "[REDACTED].txt").read_text() == "existing"
        assert sorted(p.read_text() for p in tmp_path.iterdir()) == ["existing", "new"]
    finally:
        workspace.close()


def test_model_can_read_allocated_canonical_path_from_history(tmp_path):
    secret = "model-canonical-path-credential-42713"
    config = Config.from_env({"SERVICE_KEY": secret})
    workspace = Workspace(str(tmp_path))
    request = SimpleNamespace(stage="implementation", workspace=workspace, data={})

    class InspectRead(Actions):
        def complete(self, messages):
            if len(messages) == 8:
                assert parse_json(messages[-1]["content"])["output"] == "second"
            if len(messages) == 6:
                # Consume the actual canonical allocation returned in history.
                path = parse_json(messages[-2]["content"])["path"]
                return json.dumps({"action": "read_file", "path": path})
            return super().complete(messages)

    try:
        run(request, Events(io.StringIO()), config, adapter=InspectRead([
            {"action": "write_file", "path": "[REDACTED].txt", "content": "first"},
            {"action": "write_file", "path": f"{secret}.txt", "content": "second"},
            {"action": "finish", "result_summary": "Done"},
        ]))
    finally:
        workspace.close()
