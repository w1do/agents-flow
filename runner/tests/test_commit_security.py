"""Host Git regression tests; all payloads are inert generated fixtures."""
import subprocess
from types import SimpleNamespace

import pytest

from runner.git_commit import commit
from runner.git_facts import GitError, GitFacts
from runner.workspace import Workspace
from test_git_contract import git, repository


def request(root, task_input):
    return SimpleNamespace(workspace=Workspace(str(root)), data=task_input,
                           skills=[{"content": "", "allowed_paths": ["."]}])


@pytest.mark.parametrize("process", [False, True])
def test_filters_neither_execute_nor_transform_bytes(repository, task_input, process):
    root, _ = repository
    (root / ".gitattributes").write_text("*.txt filter=audit\n")
    git(root, "config", "filter.audit.clean", "touch filter-ran; printf altered")
    git(root, "config", "filter.audit.smudge", "touch filter-ran; printf altered")
    if process:
        git(root, "config", "filter.audit.process", "touch filter-ran; exit 1")
        git(root, "config", "filter.audit.required", "true")
    (root / "tracked.txt").write_bytes(b"literal\r\n")
    req = request(root, task_input)
    result = commit(req, GitFacts(req))
    assert result["commit_sha"]
    assert not (root / "filter-ran").exists()
    assert subprocess.check_output(["git", "-C", str(root), "show", "HEAD:tracked.txt"]) == b"literal\r\n"


@pytest.mark.parametrize("kind,reason", [("pem", "git_private_key"), ("nul", "git_binary_blob"),
                                        ("binary", "git_binary_blob"), ("snapshot", "git_secret_blob")])
def test_content_rejected_even_under_public_name(repository, task_input, monkeypatch, kind, reason):
    from runner import secrets
    from secrets import token_hex
    root, base = repository
    (root / "src").mkdir()
    marker = token_hex(24)
    monkeypatch.setattr(secrets, "_active", secrets.SecretSnapshot(frozenset({marker})))
    payloads = {"pem": ("-----BEGIN " + "RSA PRIVATE KEY-----\nfixture\n").encode(),
                "nul": b"text\0text", "binary": b"\xff\xfe\x01", "snapshot": marker.encode()}
    name = "data.bin" if kind in {"nul", "binary"} else "public.txt"
    (root / "src" / name).write_bytes(payloads[kind])
    req = request(root, task_input)
    with pytest.raises(GitError, match=reason):
        commit(req, GitFacts(req))
    assert git(root, "rev-parse", "HEAD") == base


def test_new_gitlink_rejected_after_staging(repository, task_input):
    root, base = repository
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{base},src/module")
    req = request(root, task_input)
    with pytest.raises(GitError, match="git_index_type_forbidden"):
        commit(req, GitFacts(req))
    assert git(root, "rev-parse", "HEAD") == base


def test_index_empty_after_restaging_is_no_changes(repository, task_input):
    root, base = repository
    (root / "tracked.txt").write_text("staged\n")
    git(root, "add", "tracked.txt")
    (root / "tracked.txt").write_text("before\n")
    req = request(root, task_input)
    assert commit(req, GitFacts(req))["no_changes"] is True
    assert git(root, "rev-parse", "HEAD") == base


@pytest.mark.parametrize("stage", ["testing", "publication"])
def test_input_claims_cleared_on_git_failure(task_input, invoke, stage):
    git(task_input["path"], "checkout", "-b", "wrong")
    code, events = invoke(dict(task_input, stage=stage, read_only=False,
                              result_data={"commit_sha": "f" * 40, "verification": {"invented": True}}))
    data = events[-1]["result_data"]
    assert data["commit_sha"] is None
    assert "invented" not in str(data.get("verification"))
