"""One path policy across model tools, projections, commits and diagnostics."""
import io
import json
from types import SimpleNamespace

import pytest

from runner.checks import run_checks
from runner.errors import RunnerError
from runner.git_facts import GitFacts
from runner.protocol import Events
from runner.sandbox_paths import projected_worktree
from runner.workspace import Workspace
from test_git_contract import git, repository

NAMES = [".secrets/item", "private.pem", "sign.key", "id_rsa.pub", ".npmrc", ".pypirc", "local.env"]


@pytest.mark.parametrize("name", NAMES)
def test_protected_paths_hidden_everywhere(tmp_path, name):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("inert fixture")
    workspace = Workspace(str(tmp_path))
    with pytest.raises(RunnerError):
        workspace.read(name)
    with pytest.raises(RunnerError):
        workspace.write(name, "overwrite")
    assert name.split("/")[0] not in [p.rstrip("/") for p in workspace.list_files()]
    with projected_worktree(workspace) as fd:
        assert name.split("/")[0] not in __import__("os").listdir(fd)
    assert target.read_text() == "inert fixture"


def test_verification_omits_subjects_and_masks_protected_paths(repository, task_input):
    root, base = repository
    (root / "tracked.txt").write_text("change\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "private-name")
    (root / ".secrets").mkdir()
    (root / ".secrets/private-name").write_text("fixture")
    req = SimpleNamespace(workspace=Workspace(str(root)),
                          data=dict(task_input, result_data={"base_sha": base}))
    facts = GitFacts(req).verification()
    assert facts["commits"] == [git(root, "rev-parse", "HEAD")]
    assert "private-name" not in json.dumps(facts)
    assert {"code": "??", "path": "[REDACTED]", "ignored": False} in facts["status"]


@pytest.mark.parametrize("command", ["cat .secrets/private-name", "tool --file=.secrets/private-name",
                                      "cat 'src/.secrets/private name'"])
@pytest.mark.parametrize("language,available", [("sh", False), ("unsupported", True)])
def test_error_events_hide_protected_command_paths(tmp_path, monkeypatch, language, available, command):
    monkeypatch.setattr("runner.checks.shutil.which", lambda _: "/bin/false" if available else None)
    request = SimpleNamespace(workspace=Workspace(str(tmp_path)), data={}, stage="testing",
                              skills=[{"content": f"```{language}\n{command}\n```"}])
    stream = io.StringIO()
    with pytest.raises(RunnerError):
        run_checks(request, Events(stream))
    assert "private-name" not in stream.getvalue()
