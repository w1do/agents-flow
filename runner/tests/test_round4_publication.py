"""Index conflicts are reviewable publication outcomes, not failed work."""
from types import SimpleNamespace

from runner.check_results import finish_checks
from runner.git_facts import GitFacts
from test_commit_security import request
from test_git_contract import git, repository


def test_publication_succeeds_and_reports_index_conflict(repository, task_input, monkeypatch):
    from runner import check_results

    root, _ = repository
    (root / "tracked.txt").write_text("published\n")
    req = request(root, task_input)
    req.stage = "publication"
    facts = GitFacts(req)
    execute = facts.execute
    competing = None

    def run(command, *args, **kwargs):
        nonlocal competing
        if command == "commit":
            (root / "concurrent.txt").write_text("other writer\n")
            git(root, "add", "concurrent.txt")
            competing = (root / ".git/index").read_bytes()
        return execute(command, *args, **kwargs)

    monkeypatch.setattr(facts, "execute", run)
    monkeypatch.setattr(check_results, "GitFacts", lambda _: facts)
    monkeypatch.setattr(check_results, "run_checks", lambda *_: {"checks_run": 1, "checks_passed": True})
    emitted = []
    events = SimpleNamespace(emit=lambda kind, **values: emitted.append((kind, values)))
    finish_checks(req, events)
    kind, result = emitted[-1]
    assert kind == "result" and result["success"] is True
    data = result["result_data"]
    assert data["commit_sha"] == git(root, "rev-parse", "HEAD")
    assert data["verification"]["index_conflict"] is True
    assert data["verification"]["stale_index"] is True
    assert data["verification"]["worktree_clean"] is False
    assert (root / ".git/index").read_bytes() == competing
    assert "code" not in data


def test_verification_observes_real_index_after_success(repository, task_input):
    from runner.git_commit import commit

    root, _ = repository
    (root / "tracked.txt").write_text("published\n")
    req = request(root, task_input)
    facts = GitFacts(req)
    commit(req, facts)
    (root / "tracked.txt").write_text("staged by another writer\n")
    git(root, "add", "tracked.txt")
    (root / "tracked.txt").write_text("published\n")
    assert facts.verification()["worktree_clean"] is False
