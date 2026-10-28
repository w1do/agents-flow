"""Validate a private index, then publish it under Git's real index lock."""
import os
import shutil
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from .commit_outcome import Finalization


class IndexDirectory(TemporaryDirectory):
    @classmethod
    def _rmtree(cls, name, ignore_errors=False):
        # Let finalization handle the first OS error. tempfile's permission
        # recovery can recurse indefinitely on a persistent unlink EACCES.
        shutil.rmtree(name, ignore_errors=ignore_errors)


def read_index(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        return stream.read()


def _remove_owned_lock(lock, owned):
    try:
        current = lock.lstat()
        if owned is not None and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
            lock.unlink()
    except FileNotFoundError:
        pass


def synchronize(source, target, before, outcome=None, finalization=None):
    # Standalone callers already treat synchronization as best effort.
    finalization = finalization if finalization is not None else Finalization(committed=True)
    try:
        with finalization.guard():
            return _synchronize(source, target, before, finalization)
        return False
    finally:
        if outcome is not None and finalization.cleanup_failed:
            outcome["cleanup_failed"] = True


def _synchronize(source, target, before, finalization):
    lock = source.with_name(source.name + ".lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    owned, published = None, False
    try:
        try:
            with os.fdopen(fd, "wb", closefd=False) as output:
                owned = os.fstat(fd)
                if read_index(source) != before:
                    return False
                with target.open("rb") as stream:
                    shutil.copyfileobj(stream, output)
                output.flush()
                os.fsync(output.fileno())
        finally:
            os.close(fd)
        os.replace(lock, source)
        published = True
        return True
    finally:
        # After publication the path may already belong to another Git process.
        if not published:
            finalization.run(_remove_owned_lock, lock, owned)


@contextmanager
def private_index(facts):
    previous = facts.index_file
    source = Path(facts.run("rev-parse", "--git-path", "index").strip())
    if not source.is_absolute():
        source = facts.root / source
    before = read_index(source)
    # Register each finalizer independently so one failure cannot skip the next.
    with ExitStack() as stack:
        temporary = IndexDirectory(prefix="runner-private-index-", dir=source.parent)
        stack.callback(facts.finalization.run, temporary.__exit__, None, None, None)
        target = Path(temporary.__enter__()) / "index"
        stack.callback(facts.finalization.run, target.unlink, True)
        if before is not None:
            target.write_bytes(before)
        facts.index_file = target
        completed = False
        try:
            yield
            completed = True
        finally:
            try:
                if completed or facts.finalization.committed:
                    stale_before = facts.stale_index
                    facts.stale_index = True  # Remains true even if synchronization raises.
                    synchronized = synchronize(source, target, before, finalization=facts.finalization)
                    facts.stale_index = stale_before or not synchronized
            finally:
                facts.index_file = previous
