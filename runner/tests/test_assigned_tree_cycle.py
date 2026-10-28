import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runner import secrets
from runner.artifacts import copy_tree
from runner.config import Config
from runner.deepagents import run
from runner.protocol import Events
from runner.sandbox_paths import private_directory, projected_worktree
from runner.workspace import Workspace
from test_artifact_redaction import Actions


class ReadActions(Actions):
    def complete(self, messages):
        self.messages = messages
        return super().complete(messages)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_text()
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("collision", [False, True])
@pytest.mark.parametrize("depth", [0, 1, 2])
def test_assigned_names_survive_projection_model_collection_and_repeated_copy(
        tmp_path, monkeypatch, collision, depth):
    monkeypatch.setattr(secrets, "_active", secrets.SecretSnapshot())
    base = "a" * 230
    credentials = ["one-key-79451", "two-key-58263"]
    config = Config.from_env({"AGENT_PROVIDER": "stub", "SERVICE_KEY": credentials[0],
                              "OTHER_KEY": credentials[1]})
    names = [base + ending for ending in (credentials if collision else ["x", "y"])]
    original = {}
    for index, name in enumerate(names):
        path = "/".join([name] * depth + ["file" if depth else name])
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"payload {index}")
        original[path] = f"payload {index}"

    workspace = Workspace(str(tmp_path))
    try:
        with projected_worktree(workspace) as exposed:
            root = Path(f"/proc/self/fd/{exposed}")
            expected = snapshot(root)
            assert sorted(expected.values()) == ["payload 0", "payload 1"]
            if collision:
                assert any(len(part.encode()) == 255
                           for path in expected for part in path.split("/"))
            else:
                # Exact PoC: two names sharing their first 230 bytes stay distinct.
                assert expected == original
            actions = ReadActions([
                *({"action": "read_file", "path": path} for path in sorted(expected)),
                {"action": "finish", "result_summary": "Done"},
            ])
            projection = Workspace(str(root.resolve()))
            try:
                run(SimpleNamespace(stage="implementation", workspace=projection, data={}),
                    Events(io.StringIO()), config, adapter=actions)
            finally:
                projection.close()
            outputs = [json.loads(message["content"])["output"]
                       for message in actions.messages[2:] if message["role"] == "user"]
            assert outputs == [expected[path] for path in sorted(expected)]
            assert snapshot(root) == expected

        assert snapshot(tmp_path) == expected
        with private_directory() as first, private_directory() as second:
            copy_tree(workspace.fd, first)
            assert snapshot(Path(f"/proc/self/fd/{first}")) == expected
            copy_tree(workspace.fd, first)
            assert snapshot(Path(f"/proc/self/fd/{first}")) == expected
            copy_tree(first, second)
            assert snapshot(Path(f"/proc/self/fd/{second}")) == expected
    finally:
        workspace.close()
