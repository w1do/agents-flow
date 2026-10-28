"""Commit policy boundaries exercised via stdin/stdout and real Git."""

import pytest

from test_git_contract import git, publication, repository


@pytest.mark.usefixtures("requires_bwrap")
def test_already_staged_rename_includes_both_paths(repository, task_input, invoke):
    root, base = repository
    (root / "src").mkdir()
    git(root, "mv", "tracked.txt", "src/renamed.txt")
    code, events = invoke(publication(task_input))
    assert code == 0 and events[-1]["success"] is True
    data = events[-1]["result_data"]
    assert data["changed_paths"] == ["src/renamed.txt", "tracked.txt"]
    assert data["verification"]["base_sha"] == base
    assert git(root, "status", "--porcelain") == ""


@pytest.mark.usefixtures("requires_bwrap")
def test_literal_pathspec_does_not_stage_other_files(repository, task_input, invoke):
    root, _ = repository
    (root / "src").mkdir()
    (root / "src/[a].txt").write_text("literal\n")
    code, events = invoke(publication(task_input))
    assert code == 0 and events[-1]["success"] is True
    assert events[-1]["result_data"]["changed_paths"] == ["src/[a].txt"]


@pytest.mark.usefixtures("requires_bwrap")
def test_wrong_branch_cannot_commit(repository, task_input, invoke):
    root, base = repository
    git(root, "checkout", "-b", "other")
    (root / "tracked.txt").write_text("change\n")
    code, events = invoke(publication(task_input))
    assert code == 0 and events[-1]["success"] is False
    assert events[-1]["result_data"]["code"] == "git_branch_mismatch"
    assert git(root, "rev-parse", "HEAD") == base


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
@pytest.mark.usefixtures("requires_bwrap")
def test_unsafe_file_cannot_commit(repository, task_input, invoke, kind):
    import os
    root, base = repository
    (root / "src").mkdir()
    target = root / "src/link"
    if kind == "symlink":
        target.symlink_to("../tracked.txt")
    else:
        os.link(root / "tracked.txt", target)
    code, events = invoke(publication(task_input))
    assert code == 1 and events[-1]["type"] == "failure"
    assert git(root, "rev-parse", "HEAD") == base


@pytest.mark.usefixtures("requires_bwrap")
def test_commit_hooks_are_not_executed_on_host(repository, task_input, invoke):
    root, _ = repository
    hook = root / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nprintf unsafe > hook-output\nexit 1\n")
    hook.chmod(0o755)
    (root / "tracked.txt").write_text("after\n")
    code, events = invoke(publication(task_input))
    assert code == 0 and events[-1]["success"] is True
    assert not (root / "hook-output").exists()


@pytest.mark.usefixtures("requires_bwrap")
def test_failed_publication_does_not_commit(repository, task_input, invoke):
    root, base = repository
    (root / "tracked.txt").write_text("after\n")
    request = publication(task_input)
    request["skills"][0]["content"] = 'allowed_paths: ["tracked.txt"]\n```sh\nexit 7\n```'
    code, events = invoke(request)
    assert code == 0 and events[-1]["success"] is False
    assert events[-1]["result_data"]["verification"]["head_sha"] == base
    assert git(root, "rev-parse", "HEAD") == base


@pytest.mark.usefixtures("requires_bwrap")
def test_commit_in_linked_worktree_preserves_primary_repository(repository, task_input, invoke):
    root, base = repository
    linked = root / "linked-worktree"
    git(root, "worktree", "add", "-b", "task/linked", str(linked), base)
    (linked / "tracked.txt").write_text("linked change\n")
    request = publication(task_input)
    request.update(path=str(linked), worktree=str(linked), branch="task/linked",
                   task={"id": "linked", "title": "Linked task"})
    code, events = invoke(request)
    assert code == 0 and events[-1]["success"] is True
    data = events[-1]["result_data"]
    assert data["commit_sha"] == git(linked, "rev-parse", "HEAD") != base
    assert git(root, "rev-parse", "HEAD") == base
    assert (root / "tracked.txt").read_text() == "before\n"
    assert (linked / ".git").is_file()
