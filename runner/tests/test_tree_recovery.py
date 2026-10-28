import os
from pathlib import Path

import pytest

from runner import artifacts
from runner.config import Config
from runner.errors import RunnerError
from runner.sandbox_paths import projected_worktree
from runner.workspace import Workspace
from test_tree_paths import SECRETS, assert_clean_tree, seed_tree


@pytest.mark.parametrize("outcome", ["rollback", "recovery", "cleanup"])
def test_full_paths_are_clean_in_backup_rollback_and_cleanup_snapshot(tmp_path, monkeypatch, outcome):
    Config.from_env({"SERVICE_KEY": SECRETS[0], "OTHER_KEY": SECRETS[1]})
    expected = seed_tree(tmp_path)
    workspace = Workspace(str(tmp_path))
    write_bytes, rmdir = artifacts.write_bytes, os.rmdir
    failed, snapshots, backups = [], [], []
    backup_expected = None

    def observe_copy(source, target, **kwargs):
        nonlocal backup_expected
        target_path = Path(os.readlink(f"/proc/self/fd/{target}"))
        result = copy_tree(source, target, **kwargs)
        if kwargs.get("depth", 0):
            return result
        if target_path.name.startswith("runner-backup-cleanup-"):
            assert_clean_tree(target_path, backup_expected)
            snapshots.append(target_path)
        elif target_path.name.startswith(".env.runner-recovery-"):
            backup_expected = assert_clean_tree(target_path, backup_expected or expected)
            backups.append(target_path)
        return result

    def fail_write(parent, name, raw, mode):
        if parent == workspace.fd and outcome != "cleanup" and (name == "z-output" or failed):
            if name == "z-output" or outcome == "recovery":
                failed.append(name)
                raise OSError("injected publication failure")
        return write_bytes(parent, name, raw, mode)

    def fail_cleanup(name, *, dir_fd=None):
        if outcome == "cleanup" and str(name).startswith(".env.runner-recovery-") and not failed:
            failed.append(name)
            raise OSError("injected cleanup failure after backup contents were removed")
        return rmdir(name, dir_fd=dir_fd)

    copy_tree = artifacts.copy_tree
    try:
        with projected_worktree(workspace) as exposed:
            root = Path(f"/proc/self/fd/{exposed}")
            published_expected = assert_clean_tree(root, expected)
            (root / "z-output").write_text("published")
            monkeypatch.setattr(artifacts, "copy_tree", observe_copy)
            monkeypatch.setattr(artifacts, "write_bytes", fail_write)
            monkeypatch.setattr(os, "rmdir", fail_cleanup)
    except RunnerError:
        assert outcome != "cleanup"
    else:
        assert outcome == "cleanup"
    finally:
        workspace.close()
    assert failed and backups
    retained = list(tmp_path.glob(".env.runner-recovery-*"))
    if outcome == "rollback":
        assert_clean_tree(tmp_path, backup_expected)
        assert snapshots and not retained
    else:
        assert len(retained) == 1
        assert retained[0].stat().st_mode & 0o777 == 0o700
        assert_clean_tree(retained[0], backup_expected)
        if outcome == "cleanup":
            assert snapshots
            assert_clean_tree(tmp_path, published_expected | {"z-output": "published"} |
                              {f"{retained[0].name}/{p}": c for p, c in backup_expected.items()})
