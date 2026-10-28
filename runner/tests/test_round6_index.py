"""Failed cleanup after a commit preserves successful publication and conflicts."""
import errno
from pathlib import Path

import pytest

from runner.git_facts import GitFacts
from runner.private_index import synchronize
from test_git_contract import git, publication, repository


def fail_owned_unlink(monkeypatch, lock):
    unlink = Path.unlink

    def injected(path, *args, **kwargs):
        if path == lock:
            raise OSError(errno.EIO, "injected cleanup failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", injected)


@pytest.mark.parametrize("failure", ["stale", "missing_target"])
def test_synchronize_cleanup_eio_returns_failed_index_outcome(tmp_path, monkeypatch, failure):
    source, target = tmp_path / "index", tmp_path / "prepared"
    source.write_bytes(b"concurrent staging")
    if failure == "stale":
        target.write_bytes(b"prepared")
    fail_owned_unlink(monkeypatch, tmp_path / "index.lock")
    outcome = {}
    before = b"before" if failure == "stale" else source.read_bytes()
    assert synchronize(source, target, before, outcome) is False
    assert outcome == {"cleanup_failed": True}
    assert source.read_bytes() == b"concurrent staging"


def test_cli_commit_succeeds_with_cleanup_eio_and_competing_index(
        repository, task_input, invoke, monkeypatch):
    root, base = repository
    (root / "tracked.txt").write_text("published\n")
    execute = GitFacts.execute
    competing = None

    def race(facts, command, *args, **kwargs):
        nonlocal competing
        result = execute(facts, command, *args, **kwargs)
        if command == "commit":
            (root / "concurrent.txt").write_text("other writer\n")
            git(root, "add", "concurrent.txt")
            competing = (root / ".git/index").read_bytes()
        return result

    monkeypatch.setattr(GitFacts, "execute", race)
    monkeypatch.setattr("runner.check_results.run_checks",
                        lambda *_: {"checks_run": 1, "checks_passed": True})
    fail_owned_unlink(monkeypatch, root / ".git/index.lock")
    code, events = invoke(publication(task_input))
    assert code == 0 and events[-1]["type"] == "result" and events[-1]["success"] is True
    data = events[-1]["result_data"]
    assert data["commit_sha"] == git(root, "rev-parse", "HEAD") != base
    assert "code" not in data
    assert all(data["verification"][key] is True
               for key in ("stale_index", "index_conflict", "cleanup_failed"))
    assert (root / ".git/index").read_bytes() == competing
    assert (root / ".git/index.lock").exists()
