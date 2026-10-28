"""Specific transport opt-ins cannot override the final protective settings."""
import subprocess

import pytest

from runner.git_process import GitError, GitProcess
from test_git_contract import git, repository

REMOTES = {"http": "http://127.0.0.1:bad/repo", "https": "https://127.0.0.1:bad/repo",
           "ssh": "ssh://fixture.invalid/repo", "git": "git://127.0.0.1:bad/repo",
           "ftp": "ftp://127.0.0.1:bad/repo", "ftps": "ftps://127.0.0.1:bad/repo",
           "file": "file:///nonexistent", "ext": "ext::false", "unknown": "unknown://fixture.invalid/repo",
           "sftp": "sftp://fixture.invalid/repo", "rsync": "rsync::fixture.invalid/repo"}


@pytest.mark.parametrize("entry", ["execute", "invoke", "discovery"])
@pytest.mark.parametrize("protocol", REMOTES)
def test_transport_opt_ins_are_overridden(repository, monkeypatch, entry, protocol):
    root, _ = repository
    setting = f"protocol.{protocol}.allow=always"
    git(root, "config", f"protocol.{protocol}.allow", "always")
    git(root, "config", "protocol.allow", "always")
    invoke = subprocess.run
    diagnostics = []

    def capture(argv, **kwargs):
        kwargs["stderr"] = subprocess.PIPE
        result = invoke(argv, **kwargs)
        diagnostics.append(result.stderr)
        return result

    monkeypatch.setattr(subprocess, "run", capture)
    monkeypatch.setattr("runner.git_process.safety_options", lambda _: ["-c", setting])
    process = GitProcess(root)
    with pytest.raises(GitError, match="git_ls_remote_failed"):
        if entry == "execute":
            process.execute("ls-remote", REMOTES[protocol])
        else:
            process._invoke("ls-remote", REMOTES[protocol], options=["-c", setting],
                            discovery=entry == "discovery")
    assert f"transport '{protocol}' not allowed".encode() in diagnostics[-1]
