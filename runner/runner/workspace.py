"""Race-resistant worktree access using directory descriptors and no-follow opens."""

import os
import secrets
import stat
from pathlib import Path

from .errors import RunnerError

FORBIDDEN = {".git", ".agent-token"}
MAX_FILE = 256 * 1024


class Workspace:
    def __init__(self, root: str, read_only=False):
        path = Path(root)
        if not path.is_absolute() or not path.is_dir():
            raise RunnerError("worktree must be an existing absolute directory")
        self.root = path.resolve(strict=True)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.read_only = read_only

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @staticmethod
    def parts(name):
        if not isinstance(name, str) or not name or "\0" in name or os.path.isabs(name):
            raise RunnerError("Invalid workspace path")
        parts = tuple(p for p in name.split("/") if p not in ("", "."))
        if any(p == ".." or p.startswith(".env") or p in FORBIDDEN for p in parts):
            raise RunnerError("Path escapes worktree or names forbidden metadata")
        return parts

    def relative(self, name):
        return "/".join(self.parts(name))

    def open_dir(self, parts, create=False):
        current = os.dup(self.fd)
        try:
            for part in parts:
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o755, dir_fd=current)
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                os.close(current)
                current = child
            return current
        except OSError:
            os.close(current)
            raise RunnerError("Workspace directory is missing, escapes the worktree or is unsafe") from None

    def is_file(self, name):
        parts = self.parts(name)
        if not parts:
            return False
        parent = self.open_dir(parts[:-1])
        try:
            try:
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except OSError:
                return False
            try:
                info = os.fstat(fd)
                return stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def read(self, name):
        parts = self.parts(name)
        if not parts:
            raise RunnerError("Read requires a regular file")
        parent = self.open_dir(parts[:-1])
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE or info.st_nlink > 1:
                os.close(fd)
                if info.st_nlink > 1:
                    raise RunnerError("Hard-linked files are forbidden")
                raise RunnerError("Read requires a regular file of at most 256 KiB")
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                return stream.read()
        except OSError:
            raise RunnerError("Path escapes worktree or workspace file is missing or unsafe") from None
        finally:
            os.close(parent)

    def write(self, name, content):
        if self.read_only:
            raise RunnerError("Stage is read-only")
        if not isinstance(content, str) or len(content.encode()) > MAX_FILE:
            raise RunnerError("File content must be text of at most 256 KiB")
        parts = self.parts(name)
        if not parts:
            raise RunnerError("Invalid workspace path")
        parent = self.open_dir(parts[:-1], create=True)
        temporary = ".runner-" + secrets.token_hex(8)
        try:
            try:
                old = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if old.st_nlink > 1:
                    raise RunnerError("Hard-linked files are forbidden")
                if not stat.S_ISREG(old.st_mode):
                    raise RunnerError("Path escapes worktree or workspace target is unsafe")
                mode = stat.S_IMODE(old.st_mode)
            except FileNotFoundError:
                mode = 0o644
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.replace(temporary, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
        except OSError:
            raise RunnerError("Workspace write failed safely") from None
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            os.close(parent)

    def list_files(self, directory="."):
        parts = self.parts(directory)
        fd = self.open_dir(parts)
        try:
            result = []
            for name in sorted(os.listdir(fd)):
                if name.startswith(".env") or name in FORBIDDEN:
                    continue
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    result.append("/".join(parts + (name,)) + "/")
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    result.append("/".join(parts + (name,)))
                if len(result) == 1000:
                    break
            return result
        finally:
            os.close(fd)
