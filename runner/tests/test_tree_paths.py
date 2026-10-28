import re
from pathlib import Path

import pytest

from runner.config import Config
from runner.errors import RunnerError
from runner.sandbox_paths import projected_worktree
from runner.workspace import Workspace

SECRETS = ("review-synthetic-credential/part-79451", "review-synthetic-credential/part-58263")


def seed_tree(root):
    expected = {"existing"}
    (root / "[REDACTED].txt").write_text("existing")
    for index, secret in enumerate(SECRETS):
        path = root / f"{secret}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"payload {index}")
        path.chmod(0o640)
        expected.add(f"payload {index}")
    return expected


def assert_clean_tree(root, expected):
    paths = list(root.rglob("*"))
    for secret in SECRETS:
        assert all(secret not in p.relative_to(root).as_posix() for p in paths)
    contents = {p.relative_to(root).as_posix(): p.read_text() for p in paths if p.is_file()}
    if isinstance(expected, set):
        assert len(contents) == len(expected) and set(contents.values()) == expected
        assert contents["[REDACTED].txt"] == "existing"
        assert all(re.fullmatch(r"\[REDACTED\]\.txt\.[0-9a-f]{24}", p)
                   for p in contents if p != "[REDACTED].txt")
    else:
        assert contents == expected
    for path, content in contents.items():
        if content.startswith("payload"):
            assert (root / path).stat().st_mode & 0o777 == 0o640
    return contents


@pytest.mark.parametrize("phase", ["projection", "collection"])
def test_full_tree_paths_keep_colliding_files_and_permissions(tmp_path, phase):
    Config.from_env({"SERVICE_KEY": SECRETS[0], "OTHER_KEY": SECRETS[1]})
    workspace = Workspace(str(tmp_path))
    try:
        if phase == "projection":
            expected = seed_tree(tmp_path)
        with projected_worktree(workspace) as exposed:
            root = Path(f"/proc/self/fd/{exposed}")
            if phase == "projection":
                expected = assert_clean_tree(root, expected)
            else:
                expected = seed_tree(root)
        assert_clean_tree(tmp_path, expected)
    finally:
        workspace.close()


def test_full_secret_path_with_private_metadata_fails_before_host_mutation(tmp_path):
    secret = SECRETS[0]
    Config.from_env({"SERVICE_KEY": secret})
    directory = tmp_path / secret
    directory.mkdir(parents=True)
    (directory / ".env").write_text("private metadata")
    (directory / "file").write_text("original")
    inode = (directory / "file").stat().st_ino
    workspace = Workspace(str(tmp_path))
    try:
        with pytest.raises(RunnerError, match="private metadata"):
            with projected_worktree(workspace):
                pass
        assert (directory / "file").read_text() == "original"
        assert (directory / "file").stat().st_ino == inode
        assert (directory / ".env").read_text() == "private metadata"
        assert not list(tmp_path.glob(".env.runner-recovery-*"))
    finally:
        workspace.close()


@pytest.mark.parametrize("phase", ["projection", "collection"])
def test_nested_secret_directories_keep_their_own_children(tmp_path, phase):
    Config.from_env({"SERVICE_KEY": SECRETS[0], "OTHER_KEY": SECRETS[1]})

    def seed(root):
        for index, secret in enumerate(SECRETS):
            directory = root / f"nested/{secret}/inner"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "file").write_text(str(index))
        (root / "empty" / SECRETS[0]).mkdir(parents=True)

    def check(root):
        assert (root / "nested/[REDACTED]/inner/file").read_text() == "1"
        others = [p for p in (root / "nested").iterdir() if p.name.startswith("[REDACTED].")]
        assert len(others) == 1
        assert re.fullmatch(r"\[REDACTED\]\.[0-9a-f]{24}", others[0].name)
        assert (others[0] / "inner/file").read_text() == "0"
        assert not list((root / "nested/review-synthetic-credential").iterdir())
        assert (root / "empty/[REDACTED]").is_dir()
        for secret in SECRETS:
            assert all(secret not in p.relative_to(root).as_posix() for p in root.rglob("*"))

    workspace = Workspace(str(tmp_path))
    try:
        if phase == "projection":
            seed(tmp_path)
        with projected_worktree(workspace) as exposed:
            root = Path(f"/proc/self/fd/{exposed}")
            if phase == "projection":
                check(root)
            else:
                seed(root)
        check(tmp_path)
    finally:
        workspace.close()
