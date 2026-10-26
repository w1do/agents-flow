"""Fail-closed, descriptor-anchored scanner for owner-provided secret values in live tests."""

import contextlib
import os
import stat
from pathlib import Path
from typing import Final

CHUNK_SIZE: Final = 64 * 1024
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK


class ScanIncomplete(Exception):
    """The scan cannot prove that every regular file below the requested root was inspected."""

    def __init__(self) -> None:
        super().__init__("scan incomplete")


def _close(fd: int) -> None:
    """Best-effort descriptor close that never masks cancellation or leaks OS details."""
    with contextlib.suppress(OSError):
        os.close(fd)


def _before_open(_: int, __: str) -> None:
    """Test seam between directory enumeration and descriptor-anchored open."""


def _read_chunk(fd: int, size: int) -> bytes:
    return os.read(fd, size)


def _open_root_directory(root: Path) -> int:
    """Open every absolute root component without following a symlink or changing process cwd."""
    if not root.is_absolute() or ".." in root.parts:
        raise ScanIncomplete
    fd = os.open("/", _OPEN_FLAGS | os.O_DIRECTORY)
    try:
        for component in root.parts[1:]:
            if component in {"", ".", ".."}:
                raise ScanIncomplete
            child = os.open(component, _OPEN_FLAGS | os.O_DIRECTORY, dir_fd=fd)
            _close(fd)
            fd = child
        return fd
    except OSError:
        _close(fd)
        raise ScanIncomplete from None
    except BaseException:
        _close(fd)
        raise


def _scan_regular_file(fd: int, needle: bytes) -> bool:
    """Stream an already-open regular file with overlap for a boundary-spanning needle."""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ScanIncomplete
        overlap = len(needle) - 1
        tail = b""
        while chunk := _read_chunk(fd, CHUNK_SIZE):
            if needle in tail + chunk:
                return True
            tail = (tail + chunk)[-overlap:] if overlap else b""
    except OSError:
        raise ScanIncomplete from None
    return False


def contains_secret(root: Path, needle: str) -> bool:
    """Return whether ``needle`` occurs in a complete safe scan of regular files below ``root``.

    Traversal and reads use directory/file descriptors opened with ``O_NOFOLLOW``.  Any symlink,
    replacement, special file, read failure or traversal failure raises generic ``ScanIncomplete``;
    callers therefore never receive a false clean result from incomplete inspection.
    """
    if not needle:
        raise ValueError("empty needle")
    try:
        encoded = needle.encode()
        root_fd = _open_root_directory(root)
    except (OSError, UnicodeError):
        raise ScanIncomplete from None

    pending = [root_fd]
    try:
        while pending:
            directory_fd = pending.pop()
            try:
                with os.scandir(directory_fd) as entries:
                    names = sorted((entry.name for entry in entries), reverse=True)
                for name in names:
                    _before_open(directory_fd, name)
                    child_fd = os.open(name, _OPEN_FLAGS, dir_fd=directory_fd)
                    try:
                        mode = os.fstat(child_fd).st_mode
                        if stat.S_ISDIR(mode):
                            pending.append(child_fd)
                            child_fd = -1
                        elif stat.S_ISREG(mode):
                            if _scan_regular_file(child_fd, encoded):
                                return True
                        else:
                            raise ScanIncomplete
                    finally:
                        if child_fd != -1:
                            _close(child_fd)
            except OSError:
                raise ScanIncomplete from None
            finally:
                _close(directory_fd)
    finally:
        for directory_fd in pending:
            _close(directory_fd)
    return False
