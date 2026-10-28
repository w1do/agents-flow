"""Allocate model paths before redaction discards their original identity."""

import os

from .artifact_paths import PathNames
from .errors import RunnerError
from .protocol import parse_json
from .redaction import redact


class ActionReply(str):
    """Sanitized text; private attributes never enter JSON or SDK history."""


class PathIdentity:
    """Retain the last raw action path outside the SDK's lossy sanitized state."""

    def __init__(self):
        self.pending = None

    def capture(self, content):
        self.pending = None
        if not isinstance(content, str) or len(content.encode()) > 512 * 1024:
            return
        try:
            action = parse_json(content)
        except (ValueError, RunnerError, RecursionError):
            return
        if isinstance(action, dict) and action.get("action") in {"list_files", "read_file", "write_file"}:
            self.pending = (redact(content), action.get("path"))

    def reply(self, content):
        reply = ActionReply(redact(content))
        if self.pending is not None and content == self.pending[0]:
            reply.original_path = self.pending[1]
        else:
            try:
                action = parse_json(content)
            except (ValueError, RunnerError, RecursionError):
                return reply
            if isinstance(action, dict) and action.get("action") in {"list_files", "read_file", "write_file"}:
                raise RunnerError("SDK action path identity unavailable")
        return reply


class ModelPaths(PathNames):
    def __init__(self, workspace):
        self.workspace = workspace
        super().__init__(workspace.parts, self.existing)

    def existing(self, parts):
        fd = os.dup(self.workspace.fd)
        try:
            for part in parts:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            return set(os.listdir(fd))
        except FileNotFoundError:
            return set()
        except OSError:
            raise RunnerError("Unsafe model artifact directory") from None
        finally:
            os.close(fd)
