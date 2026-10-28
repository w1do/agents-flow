import errno
import os
from contextlib import nullcontext

import pytest

from runner.sandbox_paths import projected_worktree
from runner.errors import RunnerError
from runner.workspace import Workspace


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("rollback", [False, True])
def test_cleanup_eio_preserves_publication_outcome(tmp_path, monkeypatch, caplog, nested, rollback):
    import runner.artifacts as artifacts

    (tmp_path / "before").write_text("original")
    if nested:
        (tmp_path / "old-dir").mkdir()
        (tmp_path / "old-dir/source").write_text("nested original")
    workspace = Workspace(str(tmp_path))
    rmdir = os.rmdir
    failures = []
    write_bytes = artifacts.write_bytes

    def fail_publication(parent, name, raw, mode):
        if parent == workspace.fd and name == "result":
            raise OSError(errno.ENOSPC, "injected publication failure")
        return write_bytes(parent, name, raw, mode)

    def fail_once(path, *, dir_fd=None):
        parent = os.readlink(f"/proc/self/fd/{dir_fd}") if dir_fd is not None else ""
        cleanup = str(path).startswith(".env.runner-recovery-") or ".env.runner-recovery-" in parent
        if cleanup and not failures:
            failures.append(path)
            raise OSError(errno.EIO, "injected cleanup failure")
        return rmdir(path, dir_fd=dir_fd)

    try:
        outcome = pytest.raises(RunnerError, match="publication failed safely") if rollback else nullcontext()
        with outcome:
            with projected_worktree(workspace) as exposed:
                os.unlink("before", dir_fd=exposed)
                fd = os.open("result", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=exposed)
                os.write(fd, b"published")
                os.close(fd)
                monkeypatch.setattr(os, "rmdir", fail_once)
                if rollback:
                    monkeypatch.setattr(artifacts, "write_bytes", fail_publication)
        assert failures
        if rollback:
            assert (tmp_path / "before").read_text() == "original"
            assert not (tmp_path / "result").exists()
            if nested:
                assert (tmp_path / "old-dir/source").read_text() == "nested original"
        else:
            assert (tmp_path / "result").read_text() == "published"
            assert not (tmp_path / "before").exists()
        assert "cleanup" in caplog.text.lower()
        backups = list(tmp_path.glob(".env.runner-recovery-*"))
        assert len(backups) == 1
        assert (backups[0] / "before").read_text() == "original"
        if nested:
            assert (backups[0] / "old-dir/source").read_text() == "nested original"
        assert not any("runner-recovery" in name for name in workspace.list_files())
    finally:
        workspace.close()
