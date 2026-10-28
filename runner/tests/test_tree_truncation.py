import os
from pathlib import Path

import pytest

from runner import artifacts, secrets
from runner.config import Config
from runner.errors import RunnerError
from runner.sandbox_paths import private_directory, projected_worktree
from runner.workspace import Workspace


@pytest.mark.parametrize("length", [230, 231, 232])
@pytest.mark.parametrize("depth", [1, 2])
@pytest.mark.parametrize("phase", ["projection", "collection", "backup", "rollback", "cleanup"])
def test_truncated_tree_paths_remain_clean_after_unsanitized_transfers(
        tmp_path, monkeypatch, length, depth, phase):
    monkeypatch.setattr(secrets, "_active", secrets.SecretSnapshot())
    secret = "/".join(["a" * 230] * depth + ["part-79451"])
    source = "/".join(["a" * length + "x"] * depth + ["part-79451.txt"])
    Config.from_env({"SERVICE_KEY": secret})

    def seed(root):
        for index, path in enumerate([source, source.replace("79451", "58263")]):
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(f"payload {index}")
            file.chmod(0o640)

    def check(root):
        entries = [p for p in root.rglob("*")
                   if not any(part.startswith(".env") for part in p.relative_to(root).parts)]
        assert all(secret not in p.relative_to(root).as_posix() for p in entries)
        files = [p for p in entries if p.is_file()]
        assert sorted(p.read_text() for p in files) == ["payload 0", "payload 1"]
        assert all(p.stat().st_mode & 0o777 == 0o640 for p in files)
        return {p.relative_to(root).as_posix(): p.read_text() for p in files}

    copy_tree, rmdir = artifacts.copy_tree, os.rmdir
    transfers, failed = [], []

    def visible(root):
        return any(not p.name.startswith(".env") for p in root.iterdir())

    def observe_copy(source_fd, target, **kwargs):
        unchanged = not kwargs.get("sanitize", True) and not kwargs.get("depth", 0)
        source_root = Path(f"/proc/self/fd/{source_fd}")
        before = check(source_root) if unchanged and visible(source_root) else None
        result = copy_tree(source_fd, target, **kwargs)
        if not kwargs.get("depth", 0):
            root = Path(f"/proc/self/fd/{target}")
            if unchanged and visible(root):
                transfers.append(check(root))
                assert transfers[-1] == before
            if os.readlink(root).split("/")[-1].startswith(".env.runner-recovery-"):
                assert root.stat().st_mode & 0o777 == 0o700
                if visible(root):
                    check(root)
            if phase == "rollback" and unchanged and target == workspace.fd and not failed:
                failed.append("publication")
                raise OSError("injected publication failure")
        return result

    def fail_cleanup(name, *, dir_fd=None):
        if phase == "cleanup" and str(name).startswith(".env.runner-recovery-") and not failed:
            failed.append("cleanup")
            raise OSError("injected cleanup failure")
        return rmdir(name, dir_fd=dir_fd)

    monkeypatch.setattr(artifacts, "copy_tree", observe_copy)
    monkeypatch.setattr(os, "rmdir", fail_cleanup)
    # sandbox_paths imports copy_tree separately.
    monkeypatch.setattr("runner.sandbox_paths.copy_tree", observe_copy)
    workspace = Workspace(str(tmp_path))
    try:
        if phase != "collection":
            seed(tmp_path)
        if phase == "backup":
            # Publishing an empty tree still sanitizes the original backup,
            # then transfers it unchanged into the cleanup snapshot.
            with private_directory() as clean:
                artifacts.publish_tree(clean, workspace.fd)
            assert transfers
        else:
            try:
                with projected_worktree(workspace) as exposed:
                    root = Path(f"/proc/self/fd/{exposed}")
                    if phase == "collection":
                        seed(root)
                    else:
                        check(root)
            except RunnerError:
                assert phase == "rollback" and failed == ["publication"]
            else:
                assert phase != "rollback"
            expected = check(tmp_path)
            assert expected in transfers
        retained = list(tmp_path.glob(".env.runner-recovery-*"))
        if phase == "cleanup":
            assert failed == ["cleanup"] and len(retained) == 1
            assert retained[0].stat().st_mode & 0o777 == 0o700
            assert check(retained[0]) == transfers[-1]
        else:
            assert not retained
    finally:
        workspace.close()
