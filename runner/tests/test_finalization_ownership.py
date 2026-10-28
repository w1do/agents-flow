"""Cleanup faults never remove a new owner's index lock."""
import errno
import os

import pytest

from cleanup_faults import inject_cleanup
from test_commit_finalization import prepare, successful_result
from test_git_contract import git, publication, repository


@pytest.mark.parametrize("fault", ["private_unlink", "temporary_unlink", "temporary_exit", "fsync"])
def test_cli_cleanup_preserves_replaced_lock(repository, task_input, invoke, monkeypatch, fault):
    root, base = repository
    prepare(root, monkeypatch)
    source, lock = root / ".git/index", root / ".git/index.lock"
    replace = os.replace
    original_index = source.read_bytes()

    def replace_then_compete(old, new, *args, **kwargs):
        result = replace(old, new, *args, **kwargs)
        if old == lock and new == source:
            lock.write_bytes(b"new owner")
        return result

    if fault == "fsync":
        def fail_after_swap(fd):
            lock.rename(root / ".git/displaced.lock")
            lock.write_bytes(b"new owner")
            raise OSError(errno.EIO, "injected")
        monkeypatch.setattr(os, "fsync", fail_after_swap)
    else:
        monkeypatch.setattr(os, "replace", replace_then_compete)
        inject_cleanup(monkeypatch, root, fault, errno.EIO)
    code, events = invoke(publication(task_input))
    successful_result(code, events, root, base, fault == "fsync")
    assert lock.read_bytes() == b"new owner"
    if fault == "fsync":
        assert source.read_bytes() == original_index


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_finalization_preserves_result_after_cleanup_errors(repository, task_input, invoke, monkeypatch, error_type):
    from tempfile import TemporaryDirectory

    root, base = repository
    prepare(root, monkeypatch)

    def exit_(*_):
        raise error_type("injected private path")

    monkeypatch.setattr(TemporaryDirectory, "__exit__", exit_)
    code, events = invoke(publication(task_input))
    data = successful_result(code, events, root, base, False)
    assert data["degradations"] == ["post_commit_" + error_type.__name__]
    assert "injected private path" not in str(events)
