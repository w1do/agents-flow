import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.config import Config
from runner.deepagents import run
from runner.protocol import Events, parse_json
from runner.sandbox_paths import projected_worktree
from runner.workspace import Workspace
from test_artifact_redaction import Actions
from test_tree_paths import SECRETS, assert_clean_tree, seed_tree


@pytest.mark.parametrize("sdk", [False, True])
def test_projected_paths_work_in_model_cycle_and_real_sdk(tmp_path, monkeypatch, sdk):
    config = Config.from_env({"SERVICE_KEY": SECRETS[0], "OTHER_KEY": SECRETS[1],
                              "AGENT_PROVIDER": "deepagents", "OPENAI_API_KEY": "offline-tree-key",
                              "AGENT_MODEL": "offline"})
    expected = seed_tree(tmp_path)
    if sdk:
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langchain_openai import ChatOpenAI

        def generate(_self, messages, **_kwargs):
            history = json.dumps([m.model_dump() for m in messages])
            assert all(secret not in history for secret in SECRETS)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=actions.complete(messages)))])

        monkeypatch.setattr(ChatOpenAI, "_generate", generate)
    workspace = Workspace(str(tmp_path))
    output = io.StringIO()
    try:
        with projected_worktree(workspace) as exposed:
            root = Path(f"/proc/self/fd/{exposed}")
            expected = assert_clean_tree(root, expected)
            allocated = next(p for p, content in expected.items() if content == "payload 1")
            actions = Actions([
                {"action": "read_file", "path": allocated},
                {"action": "write_file", "path": allocated, "content": "updated"},
                {"action": "finish", "result_summary": "Done"},
            ])
            projection = Workspace(str(root.resolve()))
            try:
                run(SimpleNamespace(stage="implementation", workspace=projection, data={}),
                    Events(output), config, adapter=None if sdk else actions)
            finally:
                projection.close()
        expected[allocated] = "updated"
        assert_clean_tree(tmp_path, expected)
        assert parse_json(output.getvalue().splitlines()[-1])["type"] == "result"
        assert all(secret not in output.getvalue() for secret in SECRETS)
    finally:
        workspace.close()
