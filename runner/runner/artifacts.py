"""Collect the entire exposed tree into a validated, sanitized private snapshot."""

import logging
import os
import secrets
import stat
from tempfile import TemporaryDirectory

from .artifact_paths import PathNames, tree_directory
from .errors import RunnerError
from .redaction import redact_bytes
from .safe_fs import MAX_ENTRIES, MAX_TREE, clear_visible, entries, opened, read_bytes, sensitive, write_bytes
from .workspace import Workspace


def copy_tree(source, target, *, exclude=False, sanitize=True, budget=None, depth=0, paths=None, prefix=()):
    """Resolve full source paths against one pinned destination root and allocator."""
    budget = [0, 0] if budget is None else budget
    paths = PathNames(Workspace.parts) if paths is None else paths
    if depth > 64:
        raise RunnerError("Artifact tree is too deep")
    for name, fd, info in entries(source, exclude):
        budget[1] += 1
        if budget[1] > MAX_ENTRIES:
            raise RunnerError("Artifact tree has too many entries")
        relative = prefix + (name,)
        safe = tuple(paths.resolve("/".join(relative), write=True).split("/")) if sanitize else relative
        directory = stat.S_ISDIR(info.st_mode)
        with tree_directory(target, safe if directory else safe[:-1]) as child:
            if directory:
                copy_tree(fd, target, exclude=exclude, sanitize=sanitize, budget=budget,
                          depth=depth + 1, paths=paths, prefix=relative)
            else:
                raw = read_bytes(fd, info)
                budget[0] += len(raw)
                if budget[0] > MAX_TREE:
                    raise RunnerError("Artifact tree exceeds size limit")
                write_bytes(child, safe[-1], redact_bytes(raw) if sanitize else raw, info.st_mode)


def publish_tree(clean, destination):
    """Back up a redacted tree before mutation; retain it if rollback fails."""
    _validate_metadata_ancestors(destination)
    name = ".env.runner-recovery-" + secrets.token_hex(16)
    os.mkdir(name, 0o700, dir_fd=destination)
    backup = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=destination)
    retain = False
    try:
        # The sensitive prefix excludes this backup from itself, all projections
        # and model tools. Redact names and bytes before writing recovery data.
        copy_tree(destination, backup, exclude=True)
        try:
            clear_visible(destination)
            copy_tree(clean, destination, sanitize=False)
        except (OSError, UnicodeError, RecursionError, RunnerError):
            try:
                clear_visible(destination)
                copy_tree(backup, destination, sanitize=False)
            except (OSError, UnicodeError, RecursionError, RunnerError):
                retain = True
                raise RunnerError("Publication failed; redacted tree retained in .env.runner-recovery-*") from None
            raise
    finally:
        try:
            if not retain:
                _cleanup_backup(backup, name, destination)
        finally:
            os.close(backup)


def _cleanup_backup(backup, name, destination):
    """Retire a committed backup; restore its full contents on a cleanup error."""
    try:
        with TemporaryDirectory(prefix="runner-backup-cleanup-") as path:
            snapshot = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                # Keep an independent redacted copy until the final rmdir has
                # succeeded. A failed unlink/rmdir can leave backup half empty.
                copy_tree(backup, snapshot, sanitize=False)
                try:
                    clear_visible(backup)
                    os.rmdir(name, dir_fd=destination)
                except OSError:
                    copy_tree(snapshot, backup, sanitize=False)
                    raise
            finally:
                os.close(snapshot)
    except (OSError, UnicodeError, RecursionError, RunnerError):
        # Publication/rollback has already committed; preserve its outcome.
        logging.getLogger(__name__).warning("Publication backup cleanup incomplete")


def _validate_metadata_ancestors(parent, paths=None, prefix=()):
    """Do not retain a secret-bearing old directory name to preserve hidden metadata."""
    paths = PathNames(Workspace.parts) if paths is None else paths
    protected = False
    for name in sorted(os.listdir(parent)):
        if sensitive(name):
            protected = True
            continue
        relative = prefix + (name,)
        safe = paths.resolve("/".join(relative), write=True)
        with opened(parent, name) as (fd, info):
            if stat.S_ISDIR(info.st_mode) and _validate_metadata_ancestors(fd, paths, relative):
                if safe != "/".join(relative):
                    raise RunnerError("Cannot safely rename a directory containing private metadata")
                protected = True
    return protected
