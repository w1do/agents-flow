"""Public runner contract, verified against real repositories."""

import subprocess

import pytest


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).rstrip("\n")


@pytest.fixture
def repository(task_input, tmp_path):
    git(tmp_path, "init", "-b", "task/task-9")
    git(tmp_path, "config", "user.name", "Runner Test")
    git(tmp_path, "config", "user.email", "runner@example.invalid")
    (tmp_path / "tracked.txt").write_text("before\n")
    git(tmp_path, "add", "tracked.txt")
    git(tmp_path, "commit", "-m", "base")
    return tmp_path, git(tmp_path, "rev-parse", "HEAD")


def publication(task_input, paths=None):
    skill = {"category": "git", "content": 'allowed_paths: ["tracked.txt", "src/"]\n```sh\ntrue\n```'}
    if paths is not None:
        skill["allowed_paths"] = paths
    return dict(task_input, stage="publication", read_only=False, skills=[skill])


def test_testing_records_real_facts(repository, task_input, invoke):
    root, base = repository
    (root / "tracked.txt").write_text("after\n")
    (root / "new.txt").write_text("new\n")
    request = dict(task_input, stage="testing", read_only=False,
                   result_data={"changed_paths": ["invented"], "commit_sha": "f" * 40,
                                "verification": {"head_sha": "f" * 40}})
    code, events = invoke(request)
    assert code == 0
    data = events[-1]["result_data"]
    assert data["commit_sha"] is None
    assert data["base_sha"] == base
    assert data["changed_paths"] == ["new.txt", "tracked.txt"]
    assert data["verification"] == {
        "base_sha": base, "head_sha": base, "commits": [],
        "status": [{"code": "M", "path": "tracked.txt", "ignored": False},
                   {"code": "??", "path": "new.txt", "ignored": False}],
        "diff_name_only": ["tracked.txt"], "worktree_clean": False,
    }


@pytest.mark.usefixtures("requires_bwrap")
def test_publication_commits_actual_paths(repository, task_input, invoke):
    root, base = repository
    (root / "src").mkdir()
    (root / "src/a file.txt").write_text("new\n")
    (root / "tracked.txt").unlink()
    request = publication(task_input)
    request["result_data"] = {"base_sha": base, "changed_paths": ["invented"]}
    initial_index = (root / ".git/index").read_bytes()
    code, events = invoke(request)
    assert code == 0
    assert events[-1]["success"] is True
    data = events[-1]["result_data"]
    assert data["commit_sha"] == git(root, "rev-parse", "HEAD") != base
    assert data["commit_subject"] == "task(task-9): Implement task"
    assert data["changed_paths"] == ["src/a file.txt", "tracked.txt"]
    assert data["verification"]["commits"] == [data["commit_sha"]]
    assert data["verification"]["worktree_clean"] is True
    assert (root / ".git/index").read_bytes() != initial_index
    assert git(root, "status", "--porcelain") == ""
    assert (root / "src/a file.txt").read_text() == "new\n"
    assert not (root / "tracked.txt").exists()


@pytest.mark.usefixtures("requires_bwrap")
def test_no_changes_does_not_invent_commit(repository, task_input, invoke):
    root, base = repository
    code, events = invoke(publication(task_input))
    data = events[-1]["result_data"]
    assert code == 0 and events[-1]["success"] is True
    assert data["commit_sha"] is None and data["no_changes"] is True
    assert data["changed_paths"] == []
    assert git(root, "rev-parse", "HEAD") == base


@pytest.mark.parametrize("name", ["outside.txt", ".env.test", ".secrets/key", ".runner-recovery-copy/data",
                                 ".env.runner-recovery-copy/data", "src/.agent-token"])
@pytest.mark.usefixtures("requires_bwrap")
def test_forbidden_or_unallowed_paths_fail_closed(repository, task_input, invoke, name):
    root, base = repository
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fixture\n")
    request = publication(task_input, ["."] if name != "outside.txt" else None)
    code, events = invoke(request)
    assert code == 0 and events[-1]["success"] is False
    assert events[-1]["result_data"]["code"] == "git_path_forbidden"
    assert git(root, "rev-parse", "HEAD") == base


@pytest.mark.usefixtures("requires_bwrap")
def test_git_failure_is_explicit(repository, task_input, invoke):
    root, base = repository
    (root / "tracked.txt").write_text("after\n")
    git(root, "config", "user.name", "")
    git(root, "config", "user.email", "")
    code, events = invoke(publication(task_input))
    assert code == 0 and events[-1]["success"] is False
    assert events[-1]["result_data"]["code"] == "git_commit_failed"
    assert git(root, "rev-parse", "HEAD") == base
