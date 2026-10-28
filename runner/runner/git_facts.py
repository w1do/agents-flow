"""Git facts from the host worktree, independent of model-reported paths."""
import re
from pathlib import Path

from .git_process import GitError, GitProcess
from .redaction import safe_path
from .commit_outcome import Finalization


class GitFacts(GitProcess):
    def __init__(self, request):
        super().__init__(request.workspace.root)
        self.stale_index = False
        self.finalization = Finalization()
        if Path(self.run("rev-parse", "--show-toplevel").rstrip("\n")).resolve() != self.root:
            raise GitError("git_worktree_mismatch")
        self.branch = "task/" + request.data["task"]["id"]
        self.check_branch()
        data = request.data.get("result_data") or {}
        previous = data.get("verification")
        base = data.get("base_sha") or (previous.get("base_sha") if isinstance(previous, dict) else None)
        if base is not None and (not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base)):
            raise GitError("git_invalid_base")
        self.base = base or self.run("rev-parse", "HEAD").strip()
        self.run("merge-base", "--is-ancestor", self.base, "HEAD")

    @property
    def cleanup_failed(self):
        return self.finalization.cleanup_failed

    def check_branch(self):
        if self.run("symbolic-ref", "--short", "HEAD").strip() != self.branch:
            raise GitError("git_branch_mismatch")

    def status(self):
        records = self.run("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--ignore-submodules=all")
        return [{"code": entry[:2].strip(), "path": entry[3:], "ignored": entry[:2] == "!!"}
                for entry in records.split("\0") if entry]

    def changed_paths(self):
        entries = self.status()
        if any("U" in entry["code"] or entry["code"] in {"AA", "DD"} for entry in entries):
            raise GitError("git_unmerged_paths")
        return sorted({entry["path"] for entry in entries})

    def verification(self):
        status = self.status()
        names = self.run("diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                         "--name-only", "-z", self.base, "--")
        result = {
            "base_sha": self.base,
            "head_sha": self.run("rev-parse", "HEAD").strip(),
            "commits": self.run("log", "--no-show-signature", "--format=%H", self.base + "..HEAD").splitlines(),
            "status": [dict(entry, path=safe_path(entry["path"])) for entry in status],
            "diff_name_only": [safe_path(name) for name in names.split("\0") if name],
            "worktree_clean": not status,
        }
        if self.stale_index:
            result.update(index_conflict=True, stale_index=True)
        if self.cleanup_failed:
            result["cleanup_failed"] = True
        return result
