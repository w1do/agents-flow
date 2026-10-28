"""Round 4: current configuration, transport isolation and index publication."""
import subprocess

import pytest

from runner.git_commit import commit
from runner.git_facts import GitFacts
from test_commit_security import request
from test_git_contract import git, repository


def test_success_synchronizes_real_index(repository, task_input):
    root, _ = repository
    (root / "tracked.txt").write_text("changed\n")
    req = request(root, task_input)
    facts = GitFacts(req)
    assert commit(req, facts)["commit_sha"]
    assert git(root, "diff", "--cached", "--name-only") == ""
    assert git(root, "status", "--porcelain") == ""
    assert facts.verification()["worktree_clean"] is True


@pytest.mark.parametrize("race", ["stage", "lock"])
def test_index_conflict_preserves_competing_state(repository, task_input, monkeypatch, race):
    root, _ = repository
    (root / "tracked.txt").write_text("changed\n")
    req = request(root, task_input)
    facts = GitFacts(req)
    execute = facts.execute
    expected = None

    def run(command, *args, **kwargs):
        nonlocal expected
        if command == "commit":
            if race == "stage":
                (root / "other.txt").write_text("concurrent\n")
                git(root, "add", "other.txt")
            else:
                (root / ".git/index.lock").write_text("competing lock")
            expected = (root / ".git/index").read_bytes()
        return execute(command, *args, **kwargs)

    monkeypatch.setattr(facts, "execute", run)
    assert commit(req, facts)["commit_sha"]
    assert (root / ".git/index").read_bytes() == expected
    verification = facts.verification()
    assert verification["stale_index"] is True
    assert verification["index_conflict"] is True
    assert verification["worktree_clean"] is False
    if race == "lock":
        assert (root / ".git/index.lock").read_text() == "competing lock"


@pytest.mark.parametrize("location", ["worktree", "include", "global", "system"])
def test_filter_config_is_refreshed_before_every_command(repository, task_input, monkeypatch, location):
    root, _ = repository
    facts = GitFacts(request(root, task_input))
    (root / ".gitattributes").write_text("*.txt filter=late\n")
    (root / "tracked.txt").write_text("changed\n")
    config = root.parent / (root.name + "-config")
    config.write_text('[filter "late"]\nclean = "touch filter-ran; cat"\n'
                      'process = "touch filter-ran; false"\nrequired = true\n')
    if location == "worktree":
        git(root, "config", "extensions.worktreeConfig", "true")
        git(root, "config", "--worktree", "include.path", str(config))
    elif location == "include":
        git(root, "config", "include.path", str(config))
    elif location == "global":
        home = root.parent / (root.name + "-home")
        home.mkdir()
        (home / ".gitconfig").write_text(config.read_text())
        monkeypatch.setenv("HOME", str(home))
    else:
        # A wrapper substitutes the system scope for the test process only;
        # production must keep inherited GIT_CONFIG_* variables isolated.
        invoke = subprocess.run

        def with_system(argv, **kwargs):
            if "--show-origin" in argv:
                kwargs["env"]["GIT_CONFIG_SYSTEM"] = str(config)
            return invoke(argv, **kwargs)

        monkeypatch.setattr(subprocess, "run", with_system)
    facts.status()
    assert not (root / "filter-ran").exists()
    assert "filter.late.clean=cat" in facts.options


def test_external_excludes_cannot_hide_untracked(repository, task_input):
    root, _ = repository
    ignore = root.parent / (root.name + "-ignore")
    ignore.write_text("hidden.txt\n")
    git(root, "config", "core.excludesFile", str(ignore))
    git(root, "config", "status.showUntrackedFiles", "no")
    (root / "hidden.txt").write_text("untracked\n")
    facts = GitFacts(request(root, task_input))
    assert "hidden.txt" in facts.changed_paths()
    assert facts.verification()["worktree_clean"] is False


def test_missing_promisor_blob_never_invokes_transport(repository, task_input):
    root, _ = repository
    blob = git(root, "rev-parse", "HEAD:tracked.txt")
    (root / ".git/objects" / blob[:2] / blob[2:]).unlink()
    git(root, "config", "remote.origin.promisor", "true")
    git(root, "config", "remote.origin.url", "ssh://fixture.invalid/repo")
    git(root, "config", "core.sshCommand", "touch transport-ran; false")
    from runner.git_process import GitError, GitProcess
    with pytest.raises(GitError):
        GitProcess(root).run("cat-file", "blob", blob)
    assert not (root / "transport-ran").exists()
