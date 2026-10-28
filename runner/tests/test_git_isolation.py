"""Host commands must not execute repository configured programs."""
import subprocess

import pytest

from runner.git_commit import commit
from runner.git_facts import GitError, GitFacts
from test_commit_security import request
from test_git_contract import git, repository


@pytest.mark.parametrize("format", ["openpgp", "ssh"])
def test_signed_history_never_runs_verifier(repository, task_input, format):
    root, base = repository
    tree = git(root, "rev-parse", "HEAD^{tree}")
    signature = "PGP SIGNATURE" if format == "openpgp" else "SSH SIGNATURE"
    raw = (f"tree {tree}\nparent {base}\nauthor Fixture <test@example.invalid> 1 +0000\n"
           f"committer Fixture <test@example.invalid> 1 +0000\n"
           f"gpgsig -----BEGIN {signature}-----\n fixture\n -----END {signature}-----\n\nfixture\n")
    sha = subprocess.check_output(["git", "-C", str(root), "hash-object", "-t", "commit", "-w", "--stdin"],
                                  input=raw.encode()).decode().strip()
    git(root, "update-ref", "HEAD", sha)
    verifier = root / "verifier"
    verifier.write_text("#!/bin/sh\ntouch verifier-ran\nexit 1\n")
    verifier.chmod(0o755)
    git(root, "config", "gpg.program", str(verifier))
    git(root, "config", "gpg.ssh.program", str(verifier))
    git(root, "config", "gpg.format", format)
    git(root, "config", "log.showSignature", "true")
    if format == "ssh":
        allowed = root / "allowed"
        allowed.write_text("")
        git(root, "config", "gpg.ssh.allowedSignersFile", str(allowed))
    req = request(root, dict(task_input, result_data={"base_sha": base}))
    assert GitFacts(req).verification()["commits"] == [sha]
    assert not (root / "verifier-ran").exists()


def test_commit_uses_validated_private_index_during_real_index_race(repository, task_input, monkeypatch):
    root, _ = repository
    (root / "tracked.txt").write_text("safe change\n")
    req = request(root, task_input)
    facts = GitFacts(req)
    execute = facts.execute
    raced_index = None

    def race(command, *args, **kwargs):
        nonlocal raced_index
        if command == "commit":
            (root / ".Secrets").mkdir()
            (root / ".Secrets/fixture").write_text("must never commit\n")
            git(root, "add", ".Secrets/fixture")
            raced_index = (root / ".git/index").read_bytes()
        return execute(command, *args, **kwargs)

    monkeypatch.setattr(facts, "execute", race)
    result = commit(req, facts)
    assert result["changed_paths"] == ["tracked.txt"]
    assert ".Secrets/fixture" not in git(root, "ls-tree", "-r", "--name-only", "HEAD")
    assert (root / ".git/index").read_bytes() == raced_index


def test_success_publishes_validated_real_index(repository, task_input):
    root, _ = repository
    before = (root / ".git/index").read_bytes()
    (root / "tracked.txt").write_text("changed\n")
    req = request(root, task_input)
    facts = GitFacts(req)
    assert commit(req, facts)["commit_sha"]
    assert (root / ".git/index").read_bytes() != before
    assert git(root, "diff", "--cached", "--name-only") == ""
    assert facts.verification()["worktree_clean"] is True


def test_rejected_blob_does_not_modify_real_index(repository, task_input):
    root, base = repository
    before = (root / ".git/index").read_bytes()
    (root / "tracked.txt").write_text("change staged in private index\n")
    (root / "z.bin").write_bytes(b"invalid\0blob")
    req = request(root, task_input)
    with pytest.raises(GitError, match="git_binary_blob"):
        commit(req, GitFacts(req))
    assert (root / ".git/index").read_bytes() == before
    assert git(root, "rev-parse", "HEAD") == base


def test_filemode_false_preserves_executable_index_mode(repository, task_input):
    root, _ = repository
    git(root, "update-index", "--chmod=+x", "tracked.txt")
    git(root, "commit", "-m", "executable")
    git(root, "config", "core.filemode", "false")
    (root / "tracked.txt").chmod(0o644)
    (root / "tracked.txt").write_text("changed\n")
    req = request(root, task_input)
    commit(req, GitFacts(req))
    assert git(root, "ls-tree", "HEAD", "tracked.txt").startswith("100755 ")


def test_tracked_file_replaced_by_directory(repository, task_input):
    root, _ = repository
    (root / "tracked.txt").unlink()
    (root / "tracked.txt").mkdir()
    (root / "tracked.txt/child.txt").write_text("replacement\n")
    req = request(root, task_input)
    result = commit(req, GitFacts(req))
    assert result["changed_paths"] == ["tracked.txt", "tracked.txt/child.txt"]
    assert git(root, "show", "HEAD:tracked.txt/child.txt") == "replacement"
