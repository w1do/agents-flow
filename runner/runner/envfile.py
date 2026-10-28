"""Read the runner's private, mode-restricted provider configuration file."""

import os
import re
import stat

from .errors import RunnerError

ALLOWED = {"OPENAI_API_KEY", "OPENAI_BASE_URL", "AGENT_MODEL"}
KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def read_env_file(env):
    path = env.get("AGENT_FLOW_RUNNER_ENV_FILE")
    if not path:
        path = os.path.join(env.get("HOME", os.path.expanduser("~")),
                            ".config", "agents-flow", "runner.env")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    except OSError:
        raise RunnerError("Runner env file cannot be opened safely") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise RunnerError("Runner env file must be a regular file with permissions no wider than 0600")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            result = {}
            for line in stream:
                if not line.strip():
                    continue
                name, sep, value = line.rstrip("\n").partition("=")
                if not sep or not KEY.fullmatch(name) or name not in ALLOWED or name in result:
                    raise RunnerError("Runner env file must contain unique KEY=VALUE entries")
                result[name] = value
            return result
    except UnicodeError:
        raise RunnerError("Runner env file must be UTF-8") from None
    finally:
        if fd >= 0:
            os.close(fd)
