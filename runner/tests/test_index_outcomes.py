"""Validate the final prepared index, including no-op and sparse/tree entries."""
import pytest

from runner.git_commit import commit
from runner.git_facts import GitError, GitFacts
from test_commit_security import request
from test_git_contract import git, publication, repository


@pytest.mark.parametrize("mode", ["160000", "040000"])
def test_prepared_index_types_are_checked(repository, task_input, monkeypatch, mode):
    root, base = repository
    (root / "tracked.txt").write_text("changed\n")
    req = request(root, task_input)
    facts = GitFacts(req)
    original = facts.run
    prepared = False

    def run(command, *args, **kwargs):
        nonlocal prepared
        result = original(command, *args, **kwargs)
        if command == "update-index":
            prepared = True
        if command == "ls-files" and args == ("--stage", "--sparse", "-z") and prepared:
            return result + f"{mode} {base} 0\tsrc/module\0"
        return result

    monkeypatch.setattr(facts, "run", run)
    with pytest.raises(GitError, match="git_index_type_forbidden"):
        commit(req, facts)
    assert prepared
    assert git(root, "rev-parse", "HEAD") == base


@pytest.mark.usefixtures("requires_bwrap")
def test_publication_empty_diff_after_preparation_succeeds(repository, task_input, invoke):
    root, base = repository
    (root / "tracked.txt").write_text("staged\n")
    git(root, "add", "tracked.txt")
    (root / "tracked.txt").write_text("before\n")
    code, events = invoke(publication(task_input))
    assert code == 0 and events[-1]["success"] is True
    data = events[-1]["result_data"]
    assert data["commit_sha"] is None and data["no_changes"] is True
    assert data["verification"]["worktree_clean"] is True
    assert git(root, "rev-parse", "HEAD") == base


@pytest.mark.parametrize("name", [".secrets/fixture", "src/local.pem", "src/sign.key", "src/id_rsa.pub",
                                 "src/.npmrc", "src/.pypirc", "src/local.env"])
def test_protected_paths_cannot_enter_index(repository, task_input, name):
    root, base = repository
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("inert fixture")
    req = request(root, task_input)
    with pytest.raises(GitError, match="git_path_forbidden"):
        commit(req, GitFacts(req))
    assert git(root, "rev-parse", "HEAD") == base
    assert git(root, "diff", "--cached", "--name-only") == ""


def test_real_sparse_tree_is_rejected(repository, task_input):
    root, _ = repository
    for directory in ("src", "other"):
        (root / directory).mkdir()
        (root / directory / "fixture.txt").write_text("fixture\n")
    git(root, "add", "src", "other")
    git(root, "commit", "-m", "fixture directories")
    base = git(root, "rev-parse", "HEAD")
    git(root, "sparse-checkout", "init", "--cone", "--sparse-index")
    git(root, "sparse-checkout", "set", "src")
    assert "040000 " in git(root, "ls-files", "--stage", "--sparse")
    req = request(root, task_input)
    with pytest.raises(GitError, match="git_index_type_forbidden"):
        commit(req, GitFacts(req))
    assert git(root, "rev-parse", "HEAD") == base
