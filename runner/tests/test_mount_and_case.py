"""Case folding and device boundaries apply to every worktree access."""
import os
from types import SimpleNamespace

import pytest

from runner.commit_paths import validate_paths
from runner.errors import RunnerError
from runner.redaction import redact, safe_command, safe_path
from runner.safe_fs import opened, sensitive
from runner.workspace import Workspace


@pytest.mark.parametrize("name", [".Secrets", ".SECRETS", "key.PEM", ".NPMRC"])
def test_casefolded_protected_paths(tmp_path, name):
    assert sensitive(name)
    workspace = Workspace(str(tmp_path))
    try:
        with pytest.raises(RunnerError):
            workspace.write(name, "fixture")
        with pytest.raises(RunnerError):
            validate_paths(tmp_path, [name], [{"content": "", "allowed_paths": ["."]}])
        for clean in (redact, safe_path, safe_command):
            assert name not in clean("src/" + name + "/fixture")
    finally:
        workspace.close()


@pytest.mark.parametrize("operation", ["directory", "read", "write", "list", "is_file", "artifact", "commit"])
def test_mount_crossing_rejected(tmp_path, monkeypatch, operation):
    (tmp_path / "mounted").mkdir()
    (tmp_path / "mounted/file.txt").write_text("fixture")
    workspace = Workspace(str(tmp_path))
    real_fstat, real_stat, real_lstat = os.fstat, os.stat, os.lstat
    device = real_fstat(workspace.fd).st_dev

    def changed(info):
        values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        return SimpleNamespace(**(values | {"st_dev": device + 1}))

    def fstat(fd):
        info = real_fstat(fd)
        target = os.readlink(f"/proc/self/fd/{fd}")
        return changed(info) if target.startswith(str(tmp_path / "mounted")) else info

    def stat(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        return changed(info) if str(path).startswith(str(tmp_path / "mounted")) or path == "mounted" else info

    monkeypatch.setattr(os, "fstat", fstat)
    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os, "lstat", lambda path, *a, **kw: changed(real_lstat(path, *a, **kw))
                        if str(path).startswith(str(tmp_path / "mounted")) else real_lstat(path, *a, **kw))
    actions = {
        "directory": lambda: os.close(workspace.open_dir(("mounted",))),
        "read": lambda: workspace.read("mounted/file.txt"),
        "write": lambda: workspace.write("mounted/file.txt", "changed"),
        "list": workspace.list_files,
        "is_file": lambda: workspace.is_file("mounted/file.txt"),
        "artifact": lambda: _open(workspace.fd),
        "commit": lambda: validate_paths(tmp_path, ["mounted/file.txt"],
                                         [{"content": "", "allowed_paths": ["."]}]),
    }
    try:
        with pytest.raises(RunnerError, match="mount_crossing"):
            actions[operation]()
        assert (tmp_path / "mounted/file.txt").read_text() == "fixture"
    finally:
        workspace.close()


def _open(parent):
    with opened(parent, "mounted"):
        pass
