import os
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from runner.errors import RunnerError
from runner.sandbox_paths import projected_worktree
from runner.workspace import Workspace


@pytest.mark.parametrize("kind", ["fifo", "socket", "device"])
def test_special_output_is_rejected_before_host_publication(tmp_path, monkeypatch, kind):
    (tmp_path / "before").write_text("unchanged")
    workspace = Workspace(str(tmp_path))
    scripts = {
        "fifo": "import os; os.mkfifo('special')",
        "socket": "import socket; s=socket.socket(socket.AF_UNIX); s.bind('special')",
        "device": "open('special', 'w').close()",
    }
    try:
        with pytest.raises(RunnerError, match="Unsafe artifact type"):
            with projected_worktree(workspace) as fd:
                # Exercise collection after an actual child creates output. This
                # unit boundary test is independent of bwrap's syscall restrictions.
                subprocess.run([sys.executable, "-c", scripts[kind]],
                               cwd=f"/proc/self/fd/{fd}", pass_fds=(fd,), check=True)
                if kind == "device":
                    inode = os.stat("special", dir_fd=fd).st_ino
                    original = os.fstat

                    def device_stat(opened):
                        info = original(opened)
                        return SimpleNamespace(st_mode=stat.S_IFCHR) if info.st_ino == inode else info

                    monkeypatch.setattr("runner.safe_fs.os.fstat", device_stat)
        assert [p.name for p in tmp_path.iterdir()] == ["before"]
        assert (tmp_path / "before").read_text() == "unchanged"
    finally:
        workspace.close()


def test_input_device_is_never_opened_for_reading(tmp_path, monkeypatch):
    (tmp_path / "device").write_text("stand-in")
    workspace = Workspace(str(tmp_path))
    original_stat, original_open = os.fstat, os.open
    inode = (tmp_path / "device").stat().st_ino

    def device_stat(fd):
        info = original_stat(fd)
        return SimpleNamespace(st_mode=stat.S_IFCHR) if info.st_ino == inode else info

    def guarded_open(path, flags, *args, **kwargs):
        assert not str(path).startswith("/proc/self/fd/"), "Device was opened before classification"
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("runner.safe_fs.os.fstat", device_stat)
    monkeypatch.setattr("runner.safe_fs.os.open", guarded_open)
    try:
        with pytest.raises(RunnerError, match="Unsafe artifact type"):
            with projected_worktree(workspace):
                pytest.fail("Device reached shell")
    finally:
        workspace.close()
