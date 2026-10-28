"""Bounded directory listings with the workspace path and device policy."""
import os
import stat

from .safe_fs import same_device, sensitive
from .mounts import reject_mount


def list_files(workspace, directory):
    parts = workspace.parts(directory)
    fd = workspace.open_dir(parts)
    try:
        result = []
        for name in sorted(os.listdir(fd)):
            if sensitive(name):
                continue
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except OSError:
                continue
            reject_mount(workspace.root.joinpath(*parts, name), workspace.root)
            same_device(info, workspace.device)
            if stat.S_ISDIR(info.st_mode):
                result.append("/".join(parts + (name,)) + "/")
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                result.append("/".join(parts + (name,)))
            if len(result) == 1000:
                break
        return result
    finally:
        os.close(fd)
