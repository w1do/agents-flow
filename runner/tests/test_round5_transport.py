"""An explicit ext transport setting must override repository opt-ins."""
import pytest

from runner.git_process import GitError, GitProcess
from test_git_contract import git, repository


@pytest.mark.parametrize("discovery", [False, True])
def test_explicit_ext_allow_is_overridden(repository, discovery):
    root, _ = repository
    git(root, "config", "protocol.ext.allow", "always")
    assert git(root, "config", "protocol.ext.allow") == "always"
    process = GitProcess(root)
    remote = "ext::sh -c touch% transport-ran"
    with pytest.raises(GitError, match="git_ls_remote_failed"):
        if discovery:
            process._invoke("ls-remote", remote, discovery=True)
        else:
            process.execute("ls-remote", remote)
    assert not (root / "transport-ran").exists()
