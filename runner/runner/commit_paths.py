"""Explicit skill path grants and unconditional exclusions for host commits."""

import json
import re
import stat
from pathlib import PurePosixPath

from .git_facts import GitError
from .safe_fs import same_device, sensitive
from .mounts import reject_mount


def forbidden(path):
    parts = tuple(part.casefold() for part in PurePosixPath(path).parts)
    return (not parts or path.startswith("/") or ".." in parts or "\0" in path
            or any(sensitive(p) or p == ".secrets" or p.startswith(
                (".runner-", "runner-private-", "runner-backup-cleanup-")) for p in parts))


def grants(skills):
    result = []
    for skill in skills:
        declarations = [skill["allowed_paths"]] if "allowed_paths" in skill else []
        for value in re.findall(r"^allowed_paths:\s*(\[[^\n]*\])\s*$", skill["content"], re.M):
            try:
                declarations.append(json.loads(value))
            except ValueError:
                raise GitError("git_invalid_allowed_paths") from None
        for values in declarations:
            if not isinstance(values, list) or any(not isinstance(p, str) or not p for p in values):
                raise GitError("git_invalid_allowed_paths")
            if any(p != "." and forbidden(p) for p in values):
                raise GitError("git_invalid_allowed_paths")
            result.extend(values)
    return result


def validate_paths(root, paths, skills):
    allowed = grants(skills)
    device = root.stat().st_dev
    for path in paths:
        reject_mount(root / path, root)
        if forbidden(path) or not any(
            grant == "." or path == grant or (grant.endswith("/") and path.startswith(grant))
            for grant in allowed
        ):
            raise GitError("git_path_forbidden")
        current = root
        for component in PurePosixPath(path).parts:
            current /= component
            try:
                info = current.lstat()
            except (FileNotFoundError, NotADirectoryError):
                break  # Deleted paths still need staging.
            same_device(info, device)
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise GitError("git_path_forbidden")
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise GitError("git_path_forbidden")
