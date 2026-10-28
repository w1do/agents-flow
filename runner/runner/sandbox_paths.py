"""Shell gets a private projection, never a live bind of the host worktree."""

import os
from contextlib import contextmanager
from tempfile import TemporaryDirectory

from .artifacts import copy_tree, publish_tree
from .errors import RunnerError


@contextmanager
def private_directory():
    with TemporaryDirectory(prefix="runner-private-") as path:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            yield fd
        finally:
            os.close(fd)


@contextmanager
def projected_worktree(workspace):
    """Pin, filter and sanitize input; reject unsafe output before any publication."""
    try:
        with private_directory() as exposed, private_directory() as clean:
            copy_tree(workspace.fd, exposed, exclude=True)
            yield exposed
            copy_tree(exposed, clean)
            publish_tree(clean, workspace.fd)
    except (OSError, UnicodeError, RecursionError):
        raise RunnerError("Artifact collection or publication failed safely") from None
