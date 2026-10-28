import os

import pytest

from runner.errors import RunnerError
from runner.workspace import Workspace


def test_canonical_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "worktree"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("unchanged")
    (root / "link").symlink_to(outside)
    (root / "directory").symlink_to(tmp_path, target_is_directory=True)
    workspace = Workspace(str(root))
    for name in ("link", "directory/new.txt"):
        with pytest.raises(RunnerError, match="escapes"):
            workspace.write(name, "bad")
        with pytest.raises(RunnerError, match="escapes"):
            workspace.read(name)
    assert outside.read_text() == "unchanged"
    assert not (tmp_path / "new.txt").exists()


def test_hardlink_does_not_allow_read_or_write(tmp_path):
    root = tmp_path / "worktree"
    root.mkdir()
    original = tmp_path / "source.txt"
    original.write_text("outside")
    os.link(original, root / "alias.txt")
    workspace = Workspace(str(root))
    with pytest.raises(RunnerError, match="Hard-linked"):
        workspace.read("alias.txt")
    with pytest.raises(RunnerError, match="Hard-linked"):
        workspace.write("alias.txt", "changed")
    assert original.read_text() == "outside"


def test_environment_alias_is_forbidden_and_hidden(tmp_path):
    (tmp_path / "alias").symlink_to(tmp_path / ".env.local")
    (tmp_path / "normal.txt").write_text("visible")
    workspace = Workspace(str(tmp_path))
    with pytest.raises(RunnerError):
        workspace.read("alias")
    assert workspace.list_files() == ["normal.txt"]


def test_writes_preserve_executable_mode(tmp_path):
    path = tmp_path / "script.sh"
    path.write_text("old")
    path.chmod(0o755)
    Workspace(str(tmp_path)).write("script.sh", "new")
    assert path.stat().st_mode & 0o777 == 0o755
    assert path.read_text() == "new"


def test_directory_replacement_after_open_stays_anchored_to_original(tmp_path, monkeypatch):
    root = tmp_path / "worktree"
    nested = root / "sub"
    nested.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = Workspace(str(root))
    real_open = os.open
    swapped = False

    def swap_after_open(path, flags, *args, **kwargs):
        nonlocal swapped
        fd = real_open(path, flags, *args, **kwargs)
        if path == "sub" and not swapped:
            swapped = True
            os.rename(nested, root / "moved")
            nested.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(os, "open", swap_after_open)
    workspace.write("sub/new.txt", "safe")
    assert (root / "moved" / "new.txt").read_text() == "safe"
    assert not (outside / "new.txt").exists()
    with pytest.raises(RunnerError):
        workspace.write("sub/escape.txt", "blocked")
