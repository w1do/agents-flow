import os

import pytest

from runner.config import Config
from runner.errors import RunnerError
from runner.sandbox_paths import projected_worktree
from runner.workspace import Workspace


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("codec", ["utf-8", "utf-16-le", "utf-16-be"])
def test_publication_failure_preserves_redacted_tree_or_recovery(tmp_path, monkeypatch, persistent, codec):
    import runner.artifacts as artifacts

    secret = "publication-original-credential-22945"
    Config.from_env({"SERVICE_KEY": secret})
    (tmp_path / secret).write_bytes(secret.encode(codec))
    (tmp_path / secret).chmod(0o640)
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/before").write_text("nested original")
    (tmp_path / "nested/.env").write_text("private metadata")
    workspace = Workspace(str(tmp_path))
    original_write = artifacts.write_bytes
    failures = []

    def fail_destination(parent, name, raw, mode):
        if os.fstat(parent).st_ino == os.fstat(workspace.fd).st_ino and (
                name == "z-output" or (persistent and failures)):
            failures.append(name)
            raise OSError("publication disk failure")
        return original_write(parent, name, raw, mode)

    try:
        with pytest.raises(RunnerError):
            with projected_worktree(workspace) as exposed:
                for name in ("a-new", "z-output"):
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=exposed)
                    os.close(fd)
                monkeypatch.setattr(artifacts, "write_bytes", fail_destination)
        assert failures
        backups = list(tmp_path.glob(".env.runner-recovery-*"))
        recovered = backups[0] if persistent else tmp_path
        for path in recovered.rglob("*"):
            if path.is_file():
                assert secret.encode(codec) not in path.read_bytes()
            assert secret not in str(path.relative_to(recovered))
        assert (recovered / "[REDACTED]").read_bytes() == "[REDACTED]".encode(codec)
        assert (recovered / "[REDACTED]").stat().st_mode & 0o777 == 0o640
        assert (recovered / "nested/before").read_text() == "nested original"
        assert (tmp_path / "nested/.env").read_text() == "private metadata"
        if persistent:
            assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o700
            assert backups[0].name not in workspace.list_files()
        else:
            assert not backups
            assert not (tmp_path / "a-new").exists()
    finally:
        workspace.close()


def test_backup_failure_never_removes_original(tmp_path, monkeypatch):
    import runner.artifacts as artifacts

    (tmp_path / "before").write_text("original")
    workspace = Workspace(str(tmp_path))
    try:
        with pytest.raises(RunnerError):
            with projected_worktree(workspace):
                original = artifacts.copy_tree

                def fail_backup(source, target, **kwargs):
                    if source == workspace.fd:
                        raise OSError("backup failed")
                    return original(source, target, **kwargs)

                monkeypatch.setattr(artifacts, "copy_tree", fail_backup)
        assert (tmp_path / "before").read_text() == "original"
        assert list(tmp_path.iterdir()) == [tmp_path / "before"]
    finally:
        workspace.close()
