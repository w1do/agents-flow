"""Every cleanup boundary preserves commits and accumulates outcome flags."""
import errno
import io
import sys

import pytest

from cleanup_faults import compete_after_commit, inject_cleanup
from test_git_contract import git, publication, repository

ERRORS = [errno.EIO, errno.EACCES, errno.EROFS, errno.ENOSPC, errno.EINTR]
FAULTS = ["lock_unlink", "private_unlink", "temporary_unlink", "temporary_exit",
          "fsync", "lock_close", "descriptor_close", "lock_flush", "replace"]


def prepare(root, monkeypatch):
    (root / "tracked.txt").write_text("published\n")
    (root / ".git/private-metadata").write_bytes(b"private metadata")
    (root / ".git/other.lock").write_bytes(b"foreign lock")
    monkeypatch.setattr("runner.check_results.run_checks",
                        lambda *_: {"checks_run": 1, "checks_passed": True})


def successful_result(code, events, root, base, stale):
    assert code == 0
    assert [e["type"] for e in events].count("result") == 1
    assert not any(e["type"] == "failure" for e in events)
    assert events[-1]["success"] is True
    data = events[-1]["result_data"]
    assert data["commit_sha"] == git(root, "rev-parse", "HEAD") != base
    assert data["changed_paths"] == ["tracked.txt"]
    assert data["verification"]["head_sha"] == data["commit_sha"]
    assert data["verification"]["cleanup_failed"] is True
    assert data["verification"].get("stale_index", False) is stale
    assert data["verification"].get("index_conflict", False) is stale
    assert "code" not in data
    assert (root / ".git/private-metadata").read_bytes() == b"private metadata"
    assert (root / ".git/other.lock").read_bytes() == b"foreign lock"
    return data


@pytest.mark.parametrize("error", ERRORS)
@pytest.mark.parametrize("fault", FAULTS)
def test_cli_cleanup_fault_preserves_commit(repository, task_input, invoke, monkeypatch, fault, error):
    root, base = repository
    prepare(root, monkeypatch)
    before = (root / ".git/index").read_bytes()
    competing = compete_after_commit(monkeypatch, root, git) if fault == "lock_unlink" else []
    touched = inject_cleanup(monkeypatch, root, fault, error)
    code, events = invoke(publication(task_input))
    stale = fault not in {"private_unlink", "temporary_unlink", "temporary_exit"}
    successful_result(code, events, root, base, stale)
    assert touched
    if fault == "temporary_unlink":
        assert len(touched) >= 2  # Both explicit removal and TemporaryDirectory failed.
    if stale:
        assert (root / ".git/index").read_bytes() == (competing[0] if competing else before)


@pytest.mark.parametrize("error", ERRORS)
@pytest.mark.parametrize("fault", ["private_unlink", "temporary_unlink", "temporary_exit"])
def test_directory_error_keeps_prior_conflict_flags(repository, task_input, invoke, monkeypatch, fault, error):
    root, base = repository
    prepare(root, monkeypatch)
    competing = compete_after_commit(monkeypatch, root, git)
    inject_cleanup(monkeypatch, root, fault, error)
    code, events = invoke(publication(task_input))
    successful_result(code, events, root, base, True)
    assert (root / ".git/index").read_bytes() == competing[0]
    assert not (root / ".git/index.lock").exists()


@pytest.mark.parametrize("error", ERRORS)
@pytest.mark.parametrize("failure_at", ["write", "flush", "closed"])
def test_cleanup_diagnostic_failure_keeps_result(repository, task_input, invoke, monkeypatch, error, failure_at):
    root, base = repository
    prepare(root, monkeypatch)
    inject_cleanup(monkeypatch, root, "fsync", error)
    attempts = []

    class BrokenStderr:
        def write(self, value):
            attempts.append(value)
            if failure_at == "write":
                raise OSError(error, "injected diagnostic failure")

        def flush(self):
            attempts.append("flush")
            raise OSError(error, "injected flush failure")

    stderr = io.StringIO() if failure_at == "closed" else BrokenStderr()
    if failure_at == "closed":
        stderr.close()
    monkeypatch.setattr(sys, "stderr", stderr)
    code, events = invoke(publication(task_input))
    successful_result(code, events, root, base, True)
    expected = ["Publication cleanup incomplete"]
    if failure_at == "flush":
        expected += ["\n", "flush"]
    assert failure_at == "closed" or attempts == expected


@pytest.mark.parametrize("error", ERRORS)
@pytest.mark.parametrize("no_changes", [False, True])
def test_cleanup_before_commit_is_failure(repository, task_input, invoke, monkeypatch, error, no_changes):
    root, base = repository
    prepare(root, monkeypatch)
    if not no_changes:
        def fail_prepare(*_):
            raise OSError(error, "before commit")
        monkeypatch.setattr("runner.git_commit.prepare_index", fail_prepare)
    else:
        monkeypatch.setattr("runner.git_commit.prepare_index", lambda *_: False)
    touched = inject_cleanup(monkeypatch, root, "temporary_exit", error)
    code, events = invoke(publication(task_input))
    assert touched and code == 1 and events[-1]["type"] == "failure"
    assert not any(e["type"] == "result" for e in events)
    assert git(root, "rev-parse", "HEAD") == base


def test_multiple_finalizer_failures_are_accumulated(repository, task_input, invoke, monkeypatch):
    root, base = repository
    prepare(root, monkeypatch)
    competing = compete_after_commit(monkeypatch, root, git)
    lock = inject_cleanup(monkeypatch, root, "lock_unlink", errno.EIO)
    index = inject_cleanup(monkeypatch, root, "private_unlink", errno.EACCES)
    code, events = invoke(publication(task_input))
    successful_result(code, events, root, base, True)
    assert lock and index
    assert (root / ".git/index").read_bytes() == competing[0]
