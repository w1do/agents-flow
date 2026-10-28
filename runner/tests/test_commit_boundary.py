"""The receipt is authoritative; protocol output remains outside best effort."""
import io
from types import SimpleNamespace

import pytest

from runner.check_results import finish_checks
from runner.commit_outcome import Finalization
from runner.git_commit import commit
from runner.git_facts import GitFacts
from runner.protocol import Events
from test_commit_finalization import prepare
from test_commit_security import request
from test_git_contract import git, repository


def test_snapshot_flags_are_immutable_and_cannot_be_cleared_by_diagnostics():
    finalization = Finalization()
    finalization.cleanup_failed = True
    facts = SimpleNamespace(branch="task/task-9", base="b" * 40, stale_index=True)
    finalization.freeze(b"[task/task-9 " + b"a" * 40 + b"] subject\n", facts, "subject", ["tracked.txt"])
    saved = finalization.snapshot
    assert saved.success and saved.cleanup_failed and saved.stale_index and saved.index_conflict
    finalization.cleanup_failed = facts.stale_index = False
    result = finalization.result({"commit_sha": None, "branch": "wrong",
                                  "verification": {"cleanup_failed": False, "stale_index": False,
                                                   "index_conflict": False}}, facts)
    assert finalization.snapshot is saved
    assert result["commit_sha"] == saved.commit_sha and result["branch"] == saved.branch
    assert all(result["verification"][flag] for flag in ("cleanup_failed", "stale_index", "index_conflict"))


@pytest.mark.parametrize("failure_at", ["write", "flush"])
@pytest.mark.parametrize("error_type", [OSError, RuntimeError, ValueError])
def test_stdout_errors_propagate_after_commit(repository, task_input, monkeypatch, failure_at, error_type):
    root, base = repository
    prepare(root, monkeypatch)
    req = request(root, task_input)
    req.stage = "publication"
    facts = GitFacts(req)
    monkeypatch.setattr("runner.check_results.GitFacts", lambda _: facts)

    class BrokenOutput(io.StringIO):
        def write(self, value):
            if failure_at == "write":
                raise error_type("protocol write failed")
            return super().write(value)

        def flush(self):
            raise error_type("protocol flush failed")

    with pytest.raises(error_type, match="protocol"):
        finish_checks(req, Events(BrokenOutput()))
    assert facts.finalization.snapshot.commit_sha == git(root, "rev-parse", "HEAD") != base
    assert facts.finalization.degradations == []
    assert not facts.stale_index and git(root, "status", "--porcelain") == ""


def test_full_sha_receipt_does_not_decode_unrelated_git_output(repository, task_input, monkeypatch):
    root, base = repository
    prepare(root, monkeypatch)
    git(root, "config", "core.abbrev", "7")
    facts = GitFacts(request(root, task_input))
    execute = facts.execute

    def execute_(command, *args, **kwargs):
        result = execute(command, *args, **kwargs)
        if command == "commit":
            result.stdout += b"\n\xff\xfe unrelated summary bytes\n"
        return result

    monkeypatch.setattr(facts, "execute", execute_)
    result = commit(request(root, task_input), facts)
    assert len(result["commit_sha"]) == 40
    assert result["commit_sha"] == git(root, "rev-parse", "HEAD") != base


@pytest.mark.parametrize("failure_at", ["serialization", "size", "sequence"])
def test_protocol_errors_are_outside_post_commit_guard(repository, task_input, monkeypatch, failure_at):
    from runner.errors import RunnerError

    root, base = repository
    prepare(root, monkeypatch)
    req = request(root, task_input)
    req.stage = "publication"
    facts = GitFacts(req)
    monkeypatch.setattr("runner.check_results.GitFacts", lambda _: facts)
    events = Events(io.StringIO())
    if failure_at == "serialization":
        def fail(_):
            raise ValueError("serialization failed")
        monkeypatch.setattr("runner.protocol.dump_json", fail)
    elif failure_at == "size":
        req.data["result_data"] = {"large": "x" * (1024 * 1024)}
    else:
        events.terminal = True
    with pytest.raises(ValueError if failure_at == "serialization" else RunnerError):
        finish_checks(req, events)
    assert facts.finalization.snapshot.commit_sha == git(root, "rev-parse", "HEAD") != base
    assert facts.finalization.degradations == []
