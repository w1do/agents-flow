import os
import socket
import stat
from types import SimpleNamespace

import pytest

from runner.config import Config
from runner.errors import RunnerError
from runner.sandbox_paths import projected_worktree
from runner.workspace import Workspace


def test_name_collisions_never_retain_secret_and_preserve_both_files(tmp_path):
    secret = "collision/private+value-78319".replace("/", "_")
    Config.from_env({"SERVICE_KEY": secret})
    (tmp_path / "[REDACTED]").write_text("first")
    (tmp_path / secret).write_text(secret)
    (tmp_path / f"folder-{secret}").mkdir()
    workspace = Workspace(str(tmp_path))
    try:
        with projected_worktree(workspace):
            pass
        assert secret not in str(list(tmp_path.rglob("*")))
        files = [p.read_text() for p in tmp_path.iterdir() if p.is_file()]
        assert sorted(files) == ["[REDACTED]", "first"]
    finally:
        workspace.close()


@pytest.mark.parametrize("kind", ["hardlink", "symlink", "socket", "fifo", "device"])
def test_unsafe_artifact_types_fail_closed(tmp_path, kind, monkeypatch):
    path = tmp_path / "unsafe"
    listener = None
    if kind == "hardlink":
        (tmp_path / "source").write_text("data")
        os.link(tmp_path / "source", path)
    elif kind == "symlink":
        path.symlink_to("/etc/passwd")
    elif kind == "socket":
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path))
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.write_text("device stand-in")
        original = os.fstat
        inode = path.stat().st_ino

        def device_stat(fd):
            info = original(fd)
            return SimpleNamespace(st_mode=stat.S_IFCHR) if info.st_ino == inode else info

        monkeypatch.setattr("runner.safe_fs.os.fstat", device_stat)
    workspace = Workspace(str(tmp_path))
    try:
        with pytest.raises(RunnerError):
            with projected_worktree(workspace):
                pytest.fail("Unsafe input reached the shell boundary")
    finally:
        workspace.close()
        if listener:
            listener.close()


@pytest.mark.parametrize("operation", ["read", "write", "rename"])
def test_collection_io_errors_fail_stage_without_export(tmp_path, monkeypatch, operation):
    (tmp_path / "before").write_text("unchanged")
    workspace = Workspace(str(tmp_path))

    def denied(*_args, **_kwargs):
        raise OSError("injected I/O failure with private details")

    try:
        with pytest.raises(RunnerError, match="failed safely"):
            with projected_worktree(workspace) as exposed:
                fd = os.open("new-secret-output", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=exposed)
                os.write(fd, b"private")
                os.close(fd)
                target = {"read": "os.read", "write": "write_bytes", "rename": "os.replace"}[operation]
                monkeypatch.setattr(f"runner.safe_fs.{target}" if target.startswith("os.")
                                    else f"runner.artifacts.{target}", denied)
        assert (tmp_path / "before").read_text() == "unchanged"
        assert not (tmp_path / "new-secret-output").exists()
    finally:
        workspace.close()


def test_sensitive_directories_are_omitted_using_pinned_tree(tmp_path):
    original = tmp_path / "work"
    original.mkdir()
    (original / "visible").write_text("pinned tree")
    for name in (".env", ".env.d", ".env.production", ".agent-token"):
        (original / name).mkdir()
        (original / name / "credential").write_text("private")
    workspace = Workspace(str(original))
    moved = tmp_path / "moved"
    original.rename(moved)
    original.mkdir()
    (original / "decoy").write_text("wrong tree")
    try:
        with projected_worktree(workspace) as fd:
            assert os.listdir(fd) == ["visible"]
        assert (moved / "visible").read_text() == "pinned tree"
        assert (moved / ".env.d/credential").read_text() == "private"
        assert list(original.iterdir()) == [original / "decoy"]
    finally:
        workspace.close()
