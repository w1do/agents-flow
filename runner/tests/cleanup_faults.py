"""Faults scoped to the host's post-commit index publication."""
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from runner.git_facts import GitFacts


def inject_cleanup(monkeypatch, root, fault, error):
    touched = []
    lock = root / ".git/index.lock"

    def fail():
        touched.append(fault)
        raise OSError(error, "injected; must never appear in diagnostics")

    if fault in {"lock_unlink", "private_unlink"}:
        original = Path.unlink

        def unlink(path, *args, **kwargs):
            if ((fault == "lock_unlink" and path == lock)
                    or (fault == "private_unlink" and path.name == "index"
                        and path.parent.name.startswith("runner-private-index-"))):
                fail()
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
    elif fault == "temporary_unlink":
        original = os.unlink

        def unlink(path, *args, **kwargs):
            parent = kwargs.get("dir_fd")
            resolved = Path(os.readlink(f"/proc/self/fd/{parent}")) / path if parent else Path(path)
            if (resolved.name == "index" and resolved.parent.name.startswith("runner-private-index-")):
                fail()
            return original(path, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", unlink)
    elif fault == "temporary_exit":
        original = TemporaryDirectory.__exit__

        def exit_(directory, *args):
            if Path(directory.name).name.startswith("runner-private-index-"):
                fail()
            return original(directory, *args)

        monkeypatch.setattr(TemporaryDirectory, "__exit__", exit_)
    elif fault == "descriptor_close":
        original = os.close

        def close(fd):
            ours = os.readlink(f"/proc/self/fd/{fd}") == str(lock)
            original(fd)
            if ours:
                fail()

        monkeypatch.setattr(os, "close", close)
    elif fault in {"lock_close", "lock_flush"}:
        original = os.fdopen

        class Output:
            def __init__(self, stream):
                self.stream = stream

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def flush(self):
                if fault == "lock_flush":
                    fail()
                self.stream.flush()

        @contextmanager
        def fdopen(fd, *args, **kwargs):
            ours = os.readlink(f"/proc/self/fd/{fd}") == str(lock)
            with original(fd, *args, **kwargs) as stream:
                yield Output(stream) if ours else stream
            if ours and fault == "lock_close":
                fail()

        monkeypatch.setattr(os, "fdopen", fdopen)
    else:
        name = "fsync" if fault == "fsync" else "replace"
        original = getattr(os, name)

        def operation(*args, **kwargs):
            if name == "fsync" or args[:2] == (lock, root / ".git/index"):
                fail()
            return original(*args, **kwargs)

        monkeypatch.setattr(os, name, operation)
    return touched


def compete_after_commit(monkeypatch, root, git):
    execute = GitFacts.execute
    competing = []

    def execute_(facts, command, *args, **kwargs):
        result = execute(facts, command, *args, **kwargs)
        if command == "commit":
            (root / "concurrent.txt").write_text("other writer\n")
            git(root, "add", "concurrent.txt")
            competing.append((root / ".git/index").read_bytes())
        return result

    monkeypatch.setattr(GitFacts, "execute", execute_)
    return competing
