import json
import re
import secrets as random_secrets
import subprocess
import sys

import pytest

from runner import secrets
from runner.artifact_paths import PathNames, artifact_name
from runner.config import Config
from runner.errors import RunnerError
from runner.workspace import Workspace


@pytest.fixture(autouse=True)
def isolated_secrets(monkeypatch):
    monkeypatch.setattr(secrets, "_active", secrets.SecretSnapshot())


@pytest.mark.parametrize("length", [230, 231, 232, 255, 256])
@pytest.mark.parametrize("depth", [1, 2])
def test_truncation_cannot_recreate_a_secret_across_components(length, depth):
    secret = "/".join(["a" * 230] * depth + ["part-79451"])
    source = "/".join(["a" * length + "x"] * depth + ["part-79451.txt"])
    Config.from_env({"SERVICE_KEY": secret})
    assert secret not in source
    paths = PathNames(Workspace.parts)
    allocated = paths.resolve(source, write=True)
    assert secret not in allocated
    assert paths.resolve(source, write=True) == allocated
    assert paths.resolve(source) == allocated
    assert paths.resolve(allocated) == allocated
    assert all(len(part.encode()) <= 255 for part in allocated.split("/"))


def test_multibyte_names_leave_room_for_unique_collision_suffixes():
    used = set()
    allocated = [artifact_name("я" * 120 + ".txt", used) for _ in range(3)]
    assert len(set(allocated)) == 3
    assert all(len(name.encode()) <= 255 for name in allocated)


def test_final_path_is_checked_after_collision_suffix(monkeypatch):
    secret = "suffix-parent/[REDACTED].1"
    credential = "collision-credential-79451"
    Config.from_env({"SERVICE_KEY": secret, "OTHER_KEY": credential})
    tokens = iter(["1", "f" * 24])
    monkeypatch.setattr(random_secrets, "token_hex", lambda _size: next(tokens))
    paths = PathNames(Workspace.parts)
    paths.resolve("suffix-parent/[REDACTED]", write=True)
    source = f"suffix-parent/{credential}"
    allocated = paths.resolve(source, write=True)
    assert secret not in allocated
    assert allocated != "suffix-parent/[REDACTED]"
    assert paths.resolve(source, write=True) == allocated


def test_random_suffix_collisions_are_retried_without_losing_identity(monkeypatch):
    Config.from_env({"SERVICE_KEY": "credential-alpha-79451", "OTHER_KEY": "credential-beta-58263"})
    tokens = iter(["a" * 24, "a" * 24, "b" * 24])
    monkeypatch.setattr(random_secrets, "token_hex", lambda _size: next(tokens))
    paths = PathNames(Workspace.parts)
    sources = ["[REDACTED].txt", "credential-alpha-79451.txt", "credential-beta-58263.txt"]
    allocated = [paths.resolve(p, write=True) for p in sources]
    assert len(set(allocated)) == 3
    assert allocated[1:] == [f"[REDACTED].txt.{c * 24}" for c in "ab"]
    assert [paths.resolve(p, write=True) for p in sources] == allocated


def test_exhausted_random_names_fail_closed_without_claiming_a_name(monkeypatch):
    monkeypatch.setattr(random_secrets, "token_hex", lambda _size: "a" * 24)
    used = {"file", "file." + "a" * 24}
    with pytest.raises(RunnerError, match="safe artifact name"):
        artifact_name("file", used)
    assert used == {"file", "file." + "a" * 24}


def test_collision_suffixes_are_random_between_process_runs():
    script = '''
import json
from runner.artifact_paths import PathNames
from runner.config import Config
from runner.workspace import Workspace
Config.from_env({"SERVICE_KEY": "credential-alpha-79451", "OTHER_KEY": "credential-beta-58263"})
paths = PathNames(Workspace.parts)
sources = ["[REDACTED].txt", "credential-alpha-79451.txt", "credential-beta-58263.txt"]
allocated = [paths.resolve(p, write=True) for p in sources]
assert [paths.resolve(p, write=True) for p in sources] == allocated
assert [paths.resolve(p) for p in sources] == allocated
assert [paths.resolve(p) for p in allocated] == allocated
print(json.dumps(allocated))
'''
    runs = []
    for _ in range(2):
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
        allocated = json.loads(result.stdout)
        assert allocated[0] == "[REDACTED].txt"
        assert len(set(allocated)) == 3
        assert all(re.fullmatch(r"\[REDACTED\]\.txt\.[0-9a-f]{24}", p) for p in allocated[1:])
        runs.append(set(allocated[1:]))
    assert runs[0].isdisjoint(runs[1])
