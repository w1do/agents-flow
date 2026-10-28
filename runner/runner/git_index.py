"""Prepare raw blobs, then enforce index types, paths and content before commit."""
import os
import re
import stat

from .commit_paths import validate_paths
from .git_process import GitError
from .safe_fs import opened, read_bytes
from .secrets import current

PRIVATE_KEY = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")


def validate_blob(raw):
    if PRIVATE_KEY.search(raw):
        raise GitError("git_private_key")
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise GitError("git_binary_blob") from None
    if any(ord(char) < 32 and char not in "\t\n\r" for char in text) or "\x7f" in text:
        raise GitError("git_binary_blob")
    if any(value.encode() in raw for value in current().variants):
        raise GitError("git_secret_blob")


def prepare_index(request, facts, paths):
    initial = facts.run("ls-files", "--stage", "--sparse", "-z")
    modes = {entry.split("\t", 1)[1]: entry.split()[0] for entry in initial.split("\0") if entry}
    filemode = facts.run("config", "--bool", "--get", "core.filemode", ok=(0, 1)).strip() != "false"
    # Remove deletions and file/directory conflicts before adding any children.
    for path in paths:
        try:
            info = (facts.root / path).lstat()
        except (FileNotFoundError, NotADirectoryError):
            info = None
        if info is None or stat.S_ISDIR(info.st_mode):
            if modes.get(path) not in {"160000", "040000"}:
                facts.run("update-index", "--force-remove", "--", path)
    for path in paths:
        try:
            (facts.root / path).lstat()
            parts = request.workspace.parts(path)
            parent = request.workspace.open_dir(parts[:-1])
            try:
                with opened(parent, parts[-1]) as (fd, info):
                    if not stat.S_ISREG(info.st_mode):
                        continue  # Index inspection below rejects gitlinks/trees.
                    raw = read_bytes(fd, info)
                    validate_blob(raw)
                    sha = facts.run("hash-object", "--no-filters", "-w", "--stdin", raw=raw).strip()
                    mode = "100755" if info.st_mode & 0o111 else "100644"
                    if not filemode and modes.get(path) in {"100644", "100755"}:
                        mode = modes[path]
                    facts.run("update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")
            finally:
                os.close(parent)
        except (FileNotFoundError, NotADirectoryError):
            # Preserve a staged gitlink for the type check, rather than silently removing it.
            entry = facts.run("ls-files", "--stage", "-z", "--", path)
            if entry.startswith(("160000 ", "040000 ")):
                continue
            facts.run("update-index", "--force-remove", "--", path)
    staged = facts.run("ls-files", "--stage", "--sparse", "-z")
    entries = [entry.split("\t", 1) for entry in staged.split("\0") if entry]
    if any(meta.split()[0] not in {"100644", "100755"} for meta, _ in entries):
        raise GitError("git_index_type_forbidden")
    names = facts.run("diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames",
                      "--name-only", "-z").split("\0")
    changed = {name for name in names if name}
    validate_paths(facts.root, changed, request.skills)
    for meta, path in entries:
        if path in changed:
            validate_blob(facts.execute("cat-file", "blob", meta.split()[1]).stdout)
    return facts.execute("diff", "--cached", "--no-ext-diff", "--no-textconv", "--quiet", ok=(0, 1)).returncode != 0
