"""Same-device mounts and path-sensitive masking."""
import io
from pathlib import Path

import pytest

from runner.commit_paths import validate_paths
from runner.errors import RunnerError
from runner.redaction import redact, safe_command
from runner.safe_fs import opened
from runner.workspace import Workspace


@pytest.mark.parametrize("text", ["Fix KeyboardEvent.key handling", '{"event.key":"Enter"}',
                                   "const key = event.key;", {"event.key": "Enter"}])
def test_identifiers_are_not_secret_paths(text):
    assert redact(text) == text
    if isinstance(text, str):
        assert safe_command(text) == text


@pytest.mark.parametrize("text", ["key.PEM?marker=42", "src/key.PEM?marker=42,next",
                                   "src/private.key?marker=42",
                                   "key.PEM?token=[REDACTED]&marker=42",
                                   ".secrets/x?marker=42;next", '".NPMRC?marker=42" next'])
def test_complete_protected_token_is_masked(text):
    assert "42" not in redact(text)
    assert "[REDACTED]" in redact(text)


@pytest.mark.parametrize("operation", ["directory", "read", "write", "list", "is_file", "artifact", "commit"])
def test_mountinfo_rejects_same_device_mount(tmp_path, monkeypatch, operation):
    mounted = tmp_path / "mounted space"
    mounted.mkdir()
    (mounted / "file.txt").write_text("fixture")
    real_open = Path.open

    def read_mountinfo(path, *args, **kwargs):
        if str(path) == "/proc/self/mountinfo":
            escaped = str(mounted).replace(" ", r"\040")
            return io.StringIO(f"1 0 0:1 / {escaped} rw - tmpfs fixture rw\n")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read_mountinfo)
    workspace = Workspace(str(tmp_path))
    actions = {
        "directory": lambda: workspace.open_dir((mounted.name,)),
        "read": lambda: workspace.read(mounted.name + "/file.txt"),
        "write": lambda: workspace.write(mounted.name + "/file.txt", "changed"),
        "list": workspace.list_files,
        "is_file": lambda: workspace.is_file(mounted.name + "/file.txt"),
        "artifact": lambda: _open(workspace.fd, mounted.name),
        "commit": lambda: validate_paths(tmp_path, [mounted.name + "/file.txt"],
                                         [{"content": "", "allowed_paths": ["."]}]),
    }
    try:
        with pytest.raises(RunnerError, match="mount_crossing"):
            actions[operation]()
        assert (mounted / "file.txt").read_text() == "fixture"
    finally:
        workspace.close()


def _open(fd, name):
    with opened(fd, name):
        pass
