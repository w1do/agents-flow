import os

import pytest

from runner.config import Config
from runner.errors import RunnerError
from runner.sandbox_paths import projected_worktree
from runner.workspace import Workspace
from test_checks import execute


@pytest.mark.usefixtures("requires_bwrap")
def test_fifo_causes_terminal_stage_failure_without_host_changes(tmp_path, task_input, invoke):
    before = tmp_path / "before"
    before.write_text("unchanged")
    inode = before.stat().st_ino
    task_input.update(stage="testing", read_only=False, skills=[
        {"category": "testing", "content": "```sh\nmkfifo pipe\n```"}])
    code, events = invoke(task_input)
    assert code == 1 and events[-1]["type"] == "failure"
    assert events[-1]["message"] == "Unsafe artifact type"
    assert not any(event["type"] == "result" for event in events)
    assert list(tmp_path.iterdir()) == [before]
    assert before.stat().st_ino == inode and before.read_text() == "unchanged"


@pytest.mark.usefixtures("requires_bwrap")
def test_sandbox_uses_original_pinned_tree_after_host_path_swap(tmp_path, monkeypatch):
    from runner.sandbox import sandbox_args

    work = tmp_path / "work"
    work.mkdir()
    (work / "visible").write_text("original")
    moved = tmp_path / "moved"

    def swap(path, fd):
        work.rename(moved)
        work.mkdir()
        (work / "decoy").write_text("other tree")
        return sandbox_args(path, fd)

    monkeypatch.setattr("runner.checks.sandbox_args", swap)
    _, events = execute(work, "sh", "test -f visible; test ! -e decoy; printf ok >proof")
    assert events[0]["exit_code"] == 0
    assert (moved / "proof").read_text() == "ok"
    assert os.listdir(work) == ["decoy"]


def test_private_metadata_cannot_keep_an_unsanitized_directory_name(tmp_path):
    secret = "metadata-ancestor-secret-58371"
    Config.from_env({"SERVICE_KEY": secret})
    path = tmp_path / secret / ".env.d"
    path.mkdir(parents=True)
    (path / "credential").write_text("private")
    workspace = Workspace(str(tmp_path))
    try:
        with pytest.raises(RunnerError, match="private metadata"):
            with projected_worktree(workspace):
                pass
        assert list(tmp_path.iterdir()) == [tmp_path / secret]
        assert (path / "credential").read_text() == "private"
    finally:
        workspace.close()
