"""A confirmed commit survives every diagnostic, with independent index cleanup."""
import errno
import subprocess
from dataclasses import FrozenInstanceError

import pytest

from cleanup_faults import compete_after_commit, inject_cleanup
from runner.git_commit import commit
from runner.git_facts import GitError, GitFacts
from test_commit_finalization import prepare
from test_commit_security import request
from test_git_contract import git, publication, repository

STEPS = ["rev-parse", "diff-tree", "show", "status", "log", "verification"]


@pytest.mark.parametrize("step", STEPS)
@pytest.mark.parametrize("error_type", [OSError, GitError, subprocess.CalledProcessError])
@pytest.mark.parametrize("state", ["clean", "cleanup", "conflict", "both"])
def test_cli_diagnostics_preserve_snapshot_and_finalization(
        repository, task_input, invoke, monkeypatch, capsys, step, error_type, state):
    root, base = repository
    prepare(root, monkeypatch)
    competing = compete_after_commit(monkeypatch, root, git) if state in {"conflict", "both"} else []
    cleanup = state in {"cleanup", "both"}
    if cleanup:
        inject_cleanup(monkeypatch, root, "private_unlink", errno.EIO)
    run, verification = GitFacts.run, GitFacts.verification
    touched, snapshots = [], []

    def fail(facts):
        touched.append(step)
        snapshots.append(facts.finalization.snapshot)
        if error_type is subprocess.CalledProcessError:
            raise error_type(1, "injected private diagnostic")
        raise error_type("injected private diagnostic")

    def run_(facts, command, *args, **kwargs):
        if facts.finalization.committed and command == step:
            fail(facts)
        return run(facts, command, *args, **kwargs)

    def verification_(facts):
        if facts.finalization.committed and step == "verification":
            fail(facts)
        return verification(facts)

    monkeypatch.setattr(GitFacts, "run", run_)
    monkeypatch.setattr(GitFacts, "verification", verification_)
    code, events = invoke(publication(task_input))
    assert touched and code == 0
    assert events[-1]["type"] == "result" and events[-1]["success"] is True
    assert not any(event["type"] == "failure" for event in events)
    data = events[-1]["result_data"]
    sha = git(root, "rev-parse", "HEAD")
    assert data["commit_sha"] == snapshots[0].commit_sha == sha != base
    assert data["branch"] == snapshots[0].branch == "task/task-9"
    assert data["commit_subject"] == "task(task-9): Implement task"
    assert data["changed_paths"] == ["tracked.txt"]
    if step in {"diff-tree", "show"}:
        assert data["verification"]["head_sha"] == sha
    else:
        # An unavailable observation must not be fabricated from the receipt.
        assert "head_sha" not in data["verification"]
    assert data["verification"].get("cleanup_failed", False) is cleanup
    for flag in ("stale_index", "index_conflict"):
        assert data["verification"].get(flag, False) is bool(competing)
    assert len(data["degradations"]) == 1 + int(step == "rev-parse") + int(cleanup)
    assert "injected private diagnostic" not in str(events) + capsys.readouterr().err
    assert "code" not in data
    if competing:
        assert (root / ".git/index").read_bytes() == competing[0]
    else:
        assert git(root, "diff", "--cached", "--name-only") == ""
        assert git(root, "status", "--porcelain") == ""
    with pytest.raises(FrozenInstanceError):
        snapshots[0].commit_sha = base


@pytest.mark.parametrize("error_type", [OSError, GitError, subprocess.CalledProcessError])
def test_commit_error_before_snapshot_remains_failure(
        repository, task_input, invoke, monkeypatch, error_type):
    root, base = repository
    prepare(root, monkeypatch)
    before = (root / ".git/index").read_bytes()
    execute = GitFacts.execute
    touched = []

    def execute_(facts, command, *args, **kwargs):
        if command == "commit":
            touched.append(facts)
            if error_type is subprocess.CalledProcessError:
                raise error_type(1, "injected")
            raise error_type("git_commit_failed")
        return execute(facts, command, *args, **kwargs)

    monkeypatch.setattr(GitFacts, "execute", execute_)
    code, events = invoke(publication(task_input))
    assert touched and touched[0].finalization.snapshot is None
    assert code == (0 if error_type is GitError else 1)
    assert events[-1]["type"] == "failure" or events[-1]["success"] is False
    assert events[-1].get("result_data", {}).get("commit_sha") is None
    assert git(root, "rev-parse", "HEAD") == base
    assert (root / ".git/index").read_bytes() == before


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_control_flow_exceptions_propagate_but_index_is_finalized(
        repository, task_input, monkeypatch, error_type):
    root, base = repository
    prepare(root, monkeypatch)
    req = request(root, task_input)
    facts = GitFacts(req)
    run = facts.run

    def run_(command, *args, **kwargs):
        if facts.finalization.committed:
            raise error_type()
        return run(command, *args, **kwargs)

    monkeypatch.setattr(facts, "run", run_)
    with pytest.raises(error_type):
        commit(req, facts)
    assert facts.finalization.snapshot.commit_sha == git(root, "rev-parse", "HEAD") != base
    assert facts.index_file is None and not facts.stale_index
    assert git(root, "status", "--porcelain") == ""
