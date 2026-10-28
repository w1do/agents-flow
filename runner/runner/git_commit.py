"""Only the trusted host runner may commit after successful publication."""
from .commit_paths import validate_paths
from .git_facts import GitError
from .git_process import CommitIntegrityError
from .git_index import prepare_index
from .redaction import redact
from .private_index import private_index


def commit(request, facts):
    if request.workspace.read_only:
        raise GitError("git_read_only")
    facts.check_branch()
    paths = facts.changed_paths()
    validate_paths(facts.root, paths, request.skills)
    result = {}
    # One boundary owns ALL work from commit through cleanup and diagnostics.
    # Before the receipt it rethrows; afterwards identity comes from the snapshot.
    with facts.finalization.guard(cleanup=False):
        with private_index(facts):
            result.update(_commit(request, facts, paths))
    with facts.finalization.guard(cleanup=False):
        result["verification"] = facts.verification()
        snapshot = facts.finalization.snapshot
        if snapshot is not None and result["verification"]["head_sha"] != snapshot.commit_sha:
            raise CommitIntegrityError("git_head_changed")
        if not result["verification"]["worktree_clean"] and not facts.stale_index:
            raise GitError("git_worktree_dirty")
    return facts.finalization.result(result, facts)


def _commit(request, facts, paths):
    if not prepare_index(request, facts, paths):
        return {"commit_sha": None, "commit_subject": None, "changed_paths": [], "no_changes": True}
    title = request.data["task"].get("title") or "complete task"
    subject = redact("task(" + request.data["task"]["id"] + "): " + " ".join(title.split())[:80])[:200]
    prepared = facts.run("diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames",
                         "--name-only", "-z")
    facts.check_branch()
    receipt = facts.execute("commit", "--no-verify", "--cleanup=verbatim", "-m", subject).stdout
    facts.finalization.freeze(receipt, facts, subject, sorted(p for p in prepared.split("\0") if p))
    sha = facts.finalization.snapshot.commit_sha
    if facts.run("rev-parse", "HEAD").strip() != sha:
        raise CommitIntegrityError("git_head_changed")
    actual = facts.run("diff-tree", "--no-commit-id", "--no-renames", "--name-only", "-r", "-z", sha, "--")
    return {"commit_sha": sha, "commit_subject": facts.run("show", "--no-show-signature", "-s", "--format=%s", sha).rstrip("\n"),
            "changed_paths": sorted(p for p in actual.split("\0") if p), "no_changes": False}
