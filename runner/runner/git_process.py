"""Bounded host Git execution with external configuration and drivers disabled."""
import os
import subprocess

from .errors import RunnerError
from .git_config import SETTINGS, safety_options


class GitError(RunnerError):
    """A reason code only: no command arguments or Git diagnostics."""


class CommitIntegrityError(GitError):
    """Commit identity could not be trusted; never a best-effort degradation."""


class GitProcess:
    def __init__(self, root):
        self.root = root
        self.options = []
        self.index_file = None

    def execute(self, command, *args, raw=None, ok=(0,)):
        try:
            self.options = safety_options(self)
        except UnicodeError:
            raise GitError("git_invalid_text") from None
        return self._invoke(command, *args, raw=raw, ok=ok, options=self.options)

    def _invoke(self, command, *args, raw=None, ok=(0,), options=(), discovery=False):
        names = ("PATH", "LANG", "TZ", "HOME", "XDG_CONFIG_HOME") if discovery else ("PATH", "LANG", "TZ")
        env = {k: os.environ[k] for k in names if k in os.environ}
        env.update(GIT_ALLOW_PROTOCOL="", GIT_TERMINAL_PROMPT="0", GIT_LITERAL_PATHSPECS="1", GIT_NO_LAZY_FETCH="1",
                   GIT_ASKPASS="/bin/true", GIT_PAGER="cat")
        if not discovery:
            env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
        if self.index_file is not None:
            env["GIT_INDEX_FILE"] = str(self.index_file)
        argv = ["git", "--no-optional-locks", *options]
        for setting in SETTINGS:
            argv.extend(("-c", setting))
        try:
            result = subprocess.run(
                [*argv, "-C", str(self.root), command, *args], env=env,
                input=raw, stdin=subprocess.DEVNULL if raw is None else None,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60,
            )
            if result.returncode not in ok:
                raise GitError("git_" + command.replace("-", "_") + "_failed")
            return result
        except (OSError, subprocess.SubprocessError):
            raise GitError("git_" + command.replace("-", "_") + "_failed") from None

    def run(self, command, *args, **kwargs):
        try:
            return self.execute(command, *args, **kwargs).stdout.decode("utf-8")
        except UnicodeError:
            raise GitError("git_invalid_text") from None
