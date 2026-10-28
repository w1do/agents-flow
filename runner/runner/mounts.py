"""Reject known nested mounts, including bind mounts sharing the root device."""
import os
import re
from pathlib import Path

from .errors import RunnerError


def mount_points():
    with Path("/proc/self/mountinfo").open(encoding="utf-8") as stream:
        return [Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4]))
                for line in stream if len(line.split()) > 4]


def reject_mount(path, root):
    path, root = Path(path), Path(root)
    for mount in mount_points():
        if mount != root and mount.is_relative_to(root) and path.is_relative_to(mount):
            raise RunnerError("mount_crossing")


def reject_fd_mount(fd, parent=None):
    path = Path(os.readlink(f"/proc/self/fd/{fd}"))
    root = Path(os.readlink(f"/proc/self/fd/{parent}")) if parent is not None else path.parent
    reject_mount(path, root)
