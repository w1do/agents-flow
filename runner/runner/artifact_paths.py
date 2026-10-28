"""Shared full-path redaction and allocation before original identity is lost."""

import os
import secrets
from contextlib import contextmanager

from .errors import RunnerError
from .redaction import redact
from .safe_fs import sensitive


def artifact_name(name, used, parent=()):
    base = redact(name)
    if base in {"", ".", ".."} or "/" in base or sensitive(base):
        raise RunnerError("Unsafe sanitized artifact name")
    # Preserve canonical names, including previously assigned collision suffixes.
    if len(base.encode()) > 255:
        while len(base.encode()) > 230:
            base = base[:-1]
    safe = base
    for _ in range(128):
        full = "/".join(parent + (safe,))
        # Truncation and suffix allocation can create a secret across separators.
        # Replace the component entirely; further truncation cannot make it safe.
        if redact(full) != full:
            base = safe = secrets.token_hex(12)
        elif safe in used:
            # Reserve suffix space only when a collision actually needs it.
            while len(base.encode()) > 230:
                base = base[:-1]
            safe = f"{base}.{secrets.token_hex(12)}"
        else:
            used.add(safe)
            return safe
    raise RunnerError("Cannot allocate a safe artifact name")


class PathNames:
    def __init__(self, parts, existing=None):
        self.parts = parts
        self.existing = existing or (lambda _parts: set())
        self.bindings = {}
        self.claimed = {}

    def resolve(self, path, *, write=False):
        original = self.parts(path)
        sanitized = self.parts(redact("/".join(original)) or ".")
        # A secret may span separators. Match sanitized prefixes back to their
        # original prefixes before allocating names, retaining directory identity.
        origins = {self.parts(redact("/".join(original[:end]))): original[:end]
                   for end in range(1, len(original) + 1)}
        safe = ()
        for index, part in enumerate(sanitized):
            key = origins[sanitized[:index + 1]]
            claimed = self.claimed.setdefault(safe, set())
            if not write and original == sanitized and part in claimed:
                # Reads may use a canonical path returned in model history.
                # Canonical ownership wins even if a raw write has a binding.
                safe += (part,)
                continue
            if key not in self.bindings:
                used = self.existing(safe) | claimed
                # An unchanged name can intentionally edit an existing file,
                # but cannot take a name already allocated to a different path.
                if key[-1] == part and part not in claimed:
                    used.discard(part)
                name = artifact_name(part, used, safe)
                claimed.add(name)
                self.bindings[key] = name
            safe += (self.bindings[key],)
        return "/".join(safe) or "."


@contextmanager
def tree_directory(root, parts):
    """Create/open only validated destination components relative to pinned fds."""
    if not parts:
        yield root
        return
    fd = os.dup(root)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o755, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)
