"""The irreversible commit receipt and best-effort publication finalization."""
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass

from .git_process import CommitIntegrityError


@dataclass(frozen=True)
class CommitSnapshot:
    commit_sha: str
    branch: str
    subject: str
    paths: tuple
    base_sha: str
    cleanup_failed: bool
    stale_index: bool
    index_conflict: bool
    success: bool = True


class Finalization:
    def __init__(self, committed=False):
        self.committed = committed
        self.snapshot = None
        self.cleanup_failed = False
        self.degradations = []

    def freeze(self, receipt, facts, subject, paths):
        # core.abbrev=40 makes Git's own success receipt contain the full SHA.
        # Parse bytes: unrelated filenames in stdout need not be valid UTF-8.
        prefix = re.match(rb"\[[^\s\[\]]+ ([0-9a-fA-F]{40})\]", receipt)
        if prefix is None:
            raise CommitIntegrityError("git_invalid_commit_receipt")
        sha = prefix.group(1).decode("ascii").lower()
        self.snapshot = CommitSnapshot(sha, facts.branch, subject, tuple(paths), facts.base,
                                       self.cleanup_failed, facts.stale_index, facts.stale_index)
        self.committed = True

    @contextmanager
    def guard(self, cleanup=True):
        try:
            yield
        except CommitIntegrityError:
            raise
        except Exception as error:
            if not self.committed:
                raise
            self.degradations.append("post_commit_" + type(error).__name__)
            if cleanup:
                self.cleanup_failed = True
                try:
                    print("Publication cleanup incomplete", file=sys.stderr, flush=True)
                except Exception as diagnostic_error:
                    self.degradations.append("post_commit_" + type(diagnostic_error).__name__)

    def run(self, operation, *args):
        with self.guard():
            return operation(*args)

    def result(self, data, facts):
        """Project immutable identity and monotonic finalization flags, without IO."""
        snapshot = self.snapshot
        if snapshot is None:
            return data
        data.update(commit_sha=snapshot.commit_sha, branch=snapshot.branch, no_changes=False)
        data.setdefault("commit_subject", snapshot.subject)
        data.setdefault("changed_paths", list(snapshot.paths))
        verification = data.setdefault("verification", {})
        verification.setdefault("base_sha", snapshot.base_sha)
        flags = {"cleanup_failed": snapshot.cleanup_failed or self.cleanup_failed,
                 "stale_index": snapshot.stale_index or facts.stale_index,
                 "index_conflict": snapshot.index_conflict or facts.stale_index}
        for flag, value in flags.items():
            if value:
                verification[flag] = True
        if self.degradations:
            data["degradations"] = list(self.degradations)
        return data
