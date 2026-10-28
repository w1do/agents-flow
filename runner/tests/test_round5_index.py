"""Index lock ownership ends permanently when the index is published."""
import os

import pytest

from runner.private_index import synchronize


@pytest.fixture
def indexes(tmp_path):
    source, target = tmp_path / "index", tmp_path / "prepared"
    source.write_bytes(b"before")
    target.write_bytes(b"prepared")
    return source, target, source.with_name("index.lock")


def test_lock_created_between_rename_and_cleanup_survives(indexes, monkeypatch):
    source, target, lock = indexes
    replace = os.replace

    def publish_then_compete(old, new):
        replace(old, new)
        if old == lock and new == source:
            # The next Git process acquires the now-free path before cleanup.
            with lock.open("xb") as stream:
                stream.write(b"concurrent staging")

    monkeypatch.setattr(os, "replace", publish_then_compete)
    assert synchronize(source, target, b"before") is True
    assert source.read_bytes() == b"prepared"
    assert lock.read_bytes() == b"concurrent staging"


def test_existing_lock_is_preserved_on_index_conflict(indexes):
    source, target, lock = indexes
    lock.write_bytes(b"concurrent staging")
    assert synchronize(source, target, b"before") is False
    assert source.read_bytes() == b"before"
    assert lock.read_bytes() == b"concurrent staging"


def test_stale_index_removes_only_acquired_lock(indexes):
    source, target, lock = indexes
    source.write_bytes(b"concurrently staged")
    assert synchronize(source, target, b"before") is False
    assert source.read_bytes() == b"concurrently staged"
    assert not lock.exists()


@pytest.mark.parametrize("failure", ["fsync", "replace", "missing_target"])
def test_failure_before_publication_cleans_owned_lock(indexes, monkeypatch, failure):
    source, target, lock = indexes

    def fail(*args):
        raise OSError("injected failure")

    if failure == "missing_target":
        target.unlink()
    else:
        monkeypatch.setattr(os, failure, fail)
    assert synchronize(source, target, b"before") is False
    assert source.read_bytes() == b"before"
    assert not lock.exists()


def test_failure_does_not_remove_replaced_lock(indexes, monkeypatch):
    source, target, lock = indexes

    def replace_lock_then_fail(fd):
        lock.rename(lock.with_name("displaced.lock"))
        lock.write_bytes(b"concurrent staging")
        raise OSError("injected failure")

    monkeypatch.setattr(os, "fsync", replace_lock_then_fail)
    assert synchronize(source, target, b"before") is False
    assert source.read_bytes() == b"before"
    assert lock.read_bytes() == b"concurrent staging"
