"""Subjects cannot supply identities; observed HEAD divergence is a failure."""
from types import SimpleNamespace

import pytest

from runner.commit_outcome import Finalization
from runner.git_facts import GitFacts
from runner.git_process import CommitIntegrityError
from test_commit_finalization import prepare
from test_git_contract import git, publication, repository


@pytest.mark.parametrize("title", ["note " + "f" * 40 + "]", "[fake " + "f" * 40 + "]"])
def test_subject_cannot_spoof_commit_receipt(repository, task_input, invoke, monkeypatch, title):
    root, base = repository
    prepare(root, monkeypatch)
    task_input["task"]["title"] = title
    code, events = invoke(publication(task_input))
    data = events[-1]["result_data"]
    assert code == 0 and events[-1]["type"] == "result" and events[-1]["success"] is True
    assert data["commit_sha"] == data["verification"]["head_sha"] == git(root, "rev-parse", "HEAD") != base
    assert data["commit_sha"] != "f" * 40
    assert data["commit_subject"] == "task(task-9): " + title
    assert data["verification"]["commits"] == [data["commit_sha"]]
    assert "degradations" not in data


@pytest.mark.parametrize("receipt", [b"[task/x " + b"a" * 39 + b"]",
                                    b"[task/x " + b"a" * 41 + b"]",
                                    b"[task/x short] [fake " + b"a" * 40 + b"]",
                                    b"prefix [task/x " + b"a" * 40 + b"]"])
def test_receipt_requires_exact_service_prefix(receipt):
    finalization = Finalization()
    facts = SimpleNamespace(branch="task/x", base="b" * 40, stale_index=False)
    with pytest.raises(CommitIntegrityError, match="git_invalid_commit_receipt"):
        finalization.freeze(receipt, facts, "subject", [])
    assert finalization.snapshot is None and not finalization.committed


@pytest.mark.parametrize("phase", ["receipt", "verification"])
def test_head_mismatch_is_failure_with_distinct_created_and_observed_shas(
        repository, task_input, invoke, monkeypatch, phase):
    root, base = repository
    prepare(root, monkeypatch)
    execute, verification = GitFacts.execute, GitFacts.verification
    created, observed, outcomes = [], [], []

    def shift_head():
        git(root, "commit", "--allow-empty", "-m", "other writer")
        observed.append(git(root, "rev-parse", "HEAD"))

    def execute_(facts, command, *args, **kwargs):
        result = execute(facts, command, *args, **kwargs)
        if command == "commit":
            outcomes.append(facts.finalization)
            created.append(git(root, "rev-parse", "HEAD"))
            if phase == "receipt":
                shift_head()
        return result

    def verification_(facts):
        if phase == "verification" and not observed:
            shift_head()
        return verification(facts)

    monkeypatch.setattr(GitFacts, "execute", execute_)
    monkeypatch.setattr(GitFacts, "verification", verification_)
    code, events = invoke(publication(task_input))
    assert code == 1 and events[-1]["type"] == "failure"
    assert not any(event["type"] == "result" for event in events)
    data = events[-1]["result_data"]
    assert data["code"] == "git_head_changed"
    assert data["commit_sha"] == created[0] != base
    assert data["verification"]["head_sha"] == observed[0] != created[0]
    assert data["verification"]["commits"] == [observed[0], created[0]]
    assert data["verification"]["status"] == ([{"code": "M", "path": "tracked.txt", "ignored": False}]
                                               if phase == "receipt" else [])
    assert data["verification"]["worktree_clean"] is (phase == "verification")
    assert outcomes[0].degradations == [] and "degradations" not in data


def test_snapshot_projection_keeps_observed_verification():
    finalization = Finalization()
    facts = SimpleNamespace(branch="task/x", base="b" * 40, stale_index=False)
    finalization.freeze(b"[task/x " + b"a" * 40 + b"] subject", facts, "subject", [])
    observation = {"head_sha": "c" * 40, "commits": ["c" * 40], "status": [{"code": "M"}]}
    data = finalization.result({"verification": observation.copy()}, facts)
    assert data["commit_sha"] == "a" * 40 != data["verification"]["head_sha"]
    assert data["verification"] == dict(observation, base_sha="b" * 40)
