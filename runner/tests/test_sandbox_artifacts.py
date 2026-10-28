import io
import os

import pytest

from runner.checks import run_checks
from runner.config import Config
from runner.errors import RunnerError
from runner.protocol import Events
from runner.sandbox import sandbox_args
from runner.sandbox_paths import private_directory
from test_checks import execute, request


def test_bind_source_is_the_pinned_projection_even_after_path_replacement(tmp_path):
    with private_directory() as fd:
        args, fds = sandbox_args(tmp_path, fd)
        try:
            source = int(args[args.index("--bind-fd") + 1])
            assert source == fds[0]
            assert os.fstat(source).st_ino == os.fstat(fd).st_ino
            assert os.fstat(source).st_ino != tmp_path.stat().st_ino
        finally:
            for opened in fds:
                os.close(opened)


@pytest.mark.usefixtures("requires_bwrap")
def test_shell_never_sees_sensitive_directories_or_their_children(tmp_path):
    for name in (".env", ".env.d", ".env.local", ".agent-token"):
        path = tmp_path / "nested" / name
        path.mkdir(parents=True)
        (path / "key").write_text("private")
    _, events = execute(tmp_path, "sh", "test -z \"$(find nested -mindepth 1 -print -quit)\"")
    assert events[0]["exit_code"] == 0
    assert (tmp_path / "nested/.env.d/key").read_text() == "private"


@pytest.mark.usefixtures("requires_bwrap")
@pytest.mark.parametrize("command", ["ln before linked", "ln -s /etc/passwd linked",
                                     "mkdir .env.d; echo private >.env.d/key", "mkfifo pipe"])
def test_shell_unsafe_artifacts_fail_without_modifying_host(tmp_path, command):
    (tmp_path / "before").write_text("unchanged")
    req = request(tmp_path, ("sh", command))
    try:
        with pytest.raises(RunnerError):
            run_checks(req, Events(io.StringIO()))
        assert [p.name for p in tmp_path.iterdir()] == ["before"]
        assert (tmp_path / "before").read_text() == "unchanged"
    finally:
        req.workspace.close()


@pytest.mark.usefixtures("requires_bwrap")
def test_shell_utf16_output_and_name_collisions_are_sanitized(tmp_path):
    secret = "shell-binary-credential-451987"
    Config.from_env({"SERVICE_KEY": secret})
    command = ("from pathlib import Path\n"
               "Path('[REDACTED]').write_text('existing')\n"
               f"Path('{secret}').write_bytes('{secret}'.encode('utf-16-le'))\n"
               f"Path('other-{secret}').write_bytes('{secret}'.encode('utf-16-be'))")
    _, events = execute(tmp_path, "python3", command)
    assert events[0]["exit_code"] == 0
    assert len(list(tmp_path.iterdir())) == 3
    for path in tmp_path.iterdir():
        assert secret not in path.name
        for codec in ("utf-8", "utf-16-le", "utf-16-be"):
            assert secret.encode(codec) not in path.read_bytes()


@pytest.mark.usefixtures("requires_bwrap")
def test_shell_changes_and_deletions_are_published_only_after_exit(tmp_path):
    (tmp_path / "remove").write_text("before")
    (tmp_path / "change").write_text("before")
    _, events = execute(tmp_path, "sh", "rm remove; printf after >change; mkdir new; printf ok >new/file")
    assert events[0]["exit_code"] == 0
    assert not (tmp_path / "remove").exists()
    assert (tmp_path / "change").read_text() == "after"
    assert (tmp_path / "new/file").read_text() == "ok"
