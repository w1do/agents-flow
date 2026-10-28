"""Descriptor-relative filesystem primitives; unsafe entries always fail closed."""

import os
import secrets
import stat
from contextlib import contextmanager

from .errors import RunnerError
from .mounts import reject_fd_mount

MAX_FILE = 16 * 1024 * 1024
MAX_TREE = 64 * 1024 * 1024
MAX_ENTRIES = 10000


def sensitive(name):
    name = name.casefold()
    return (name.startswith((".env", "id_rsa", ".secrets")) or name.endswith((".pem", ".key", ".env"))
            or name in {".agent-token", ".git", ".secrets", ".npmrc", ".pypirc"})


def same_device(info, device):
    if info.st_dev != device:
        raise RunnerError("mount_crossing")


def checked_fd(fd, device):
    try:
        same_device(os.fstat(fd), device)
        reject_fd_mount(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def opened(parent, name):
    # Inspect a pinned inode without opening a device or blocking on a FIFO.
    pinned = os.open(name, os.O_PATH | os.O_NOFOLLOW, dir_fd=parent)
    try:
        reject_fd_mount(pinned, parent)
        info = os.fstat(pinned)
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise RunnerError("Unsafe artifact type")
        same_device(info, os.fstat(parent).st_dev)
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise RunnerError("Hard-linked artifacts are forbidden")
        # This is a trusted proc-fd reference, never the mutable input pathname.
        fd = os.open(f"/proc/self/fd/{pinned}", os.O_RDONLY | os.O_NONBLOCK)
        try:
            yield fd, info
        finally:
            os.close(fd)
    finally:
        os.close(pinned)


def entries(parent, exclude=False):
    for name in sorted(os.listdir(parent)):
        name.encode("utf-8")  # Reject undecodable filenames instead of exporting raw bytes.
        if sensitive(name):
            if exclude:
                continue
            raise RunnerError("Sensitive artifact path is forbidden")
        with opened(parent, name) as (fd, info):
            yield name, fd, info


def read_bytes(fd, info):
    if info.st_size > MAX_FILE:
        raise RunnerError("Artifact exceeds size limit")
    chunks, size = [], 0
    while chunk := os.read(fd, min(65536, MAX_FILE + 1 - size)):
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_FILE:
            raise RunnerError("Artifact exceeds size limit")
    after = os.fstat(fd)
    if after.st_nlink != 1 or (after.st_size, after.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
        raise RunnerError("Artifact changed during collection")
    return b"".join(chunks)


def write_bytes(parent, name, raw, mode):
    temporary = ".runner-" + secrets.token_hex(16)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     mode & 0o777, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


def clear_visible(parent):
    """Delete exposed entries, preserving secret metadata and its ancestors."""
    preserved = False
    for name in os.listdir(parent):
        if sensitive(name):
            preserved = True
            continue
        with opened(parent, name) as (fd, info):
            keep = stat.S_ISDIR(info.st_mode) and clear_visible(fd)
            if keep:
                preserved = True
            elif stat.S_ISDIR(info.st_mode):
                os.rmdir(name, dir_fd=parent)
            else:
                os.unlink(name, dir_fd=parent)
    return preserved
