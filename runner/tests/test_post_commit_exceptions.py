"""Ordinary exceptions degrade only after the irreversible commit boundary."""
import errno
import sys
from tempfile import TemporaryDirectory

import pytest

from cleanup_faults import inject_cleanup
from runner.git_facts import GitFacts
from test_commit_finalization import prepare, successful_result
from test_git_contract import git, publication, repository


def inject_exception(monkeypatch, phase, error_type):
    touched = []

    def fail(*_):
        touched.append(phase)
        raise error_type("private/path?secret=never-export")

    if phase == "temporary_exit":
        monkeypatch.setattr(TemporaryDirectory, "__exit__", fail)
    else:
        monkeypatch.setattr(GitFacts, "verification", fail)
    return touched


@pytest.mark.parametrize("phase", ["temporary_exit", "verification"])
@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_astra_exceptions_keep_sha_and_accumulated_flags(
        repository, task_input, invoke, monkeypatch, capsys, phase, error_type):
    root, base = repository
    prepare(root, monkeypatch)
    inject_cleanup(monkeypatch, root, "fsync", errno.EIO)
    touched = inject_exception(monkeypatch, phase, error_type)
    code, events = invoke(publication(task_input))
    assert touched
    assert code == 0 and events[-1]["type"] == "result" and events[-1]["success"] is True
    data = events[-1]["result_data"]
    assert data["commit_sha"] == git(root, "rev-parse", "HEAD") != base
    assert data["changed_paths"] == ["tracked.txt"]
    assert all(data["verification"][flag] for flag in ("cleanup_failed", "stale_index", "index_conflict"))
    assert data["degradations"] == ["post_commit_OSError", "post_commit_" + error_type.__name__]
    assert "private/path" not in str(events) + capsys.readouterr().err
    assert not any(event["type"] == "failure" for event in events)


@pytest.mark.parametrize("phase", ["temporary_exit", "verification"])
@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_same_exceptions_before_commit_remain_failures(
        repository, task_input, invoke, monkeypatch, phase, error_type):
    root, base = repository
    prepare(root, monkeypatch)
    monkeypatch.setattr("runner.git_commit.prepare_index", lambda *_: False)
    touched = inject_exception(monkeypatch, phase, error_type)
    code, events = invoke(publication(task_input))
    assert touched and code == 1 and events[-1]["type"] == "failure"
    assert not any(event["type"] == "result" for event in events)
    assert git(root, "rev-parse", "HEAD") == base


@pytest.mark.parametrize("phase", ["temporary_exit", "verification"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_control_exceptions_escape_post_commit(
        repository, task_input, invoke, monkeypatch, phase, error_type):
    root, base = repository
    prepare(root, monkeypatch)
    touched = inject_exception(monkeypatch, phase, error_type)
    with pytest.raises(error_type):
        invoke(publication(task_input))
    assert touched and git(root, "rev-parse", "HEAD") != base
    assert git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_stderr_exceptions_are_recorded_without_losing_result(
        repository, task_input, invoke, monkeypatch, error_type):
    root, base = repository
    prepare(root, monkeypatch)
    inject_cleanup(monkeypatch, root, "fsync", errno.EIO)

    class BrokenStderr:
        def write(self, _):
            raise error_type("private/path?secret=never-export")

    monkeypatch.setattr(sys, "stderr", BrokenStderr())
    code, events = invoke(publication(task_input))
    data = successful_result(code, events, root, base, True)
    assert data["degradations"] == ["post_commit_OSError", "post_commit_" + error_type.__name__]
    assert "private/path" not in str(events)
