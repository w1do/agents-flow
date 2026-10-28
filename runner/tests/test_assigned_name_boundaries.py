import re

import pytest

from runner import secrets
from runner.artifact_paths import PathNames, artifact_name
from runner.workspace import Workspace


@pytest.fixture(autouse=True)
def isolated_secrets(monkeypatch):
    monkeypatch.setattr(secrets, "_active", secrets.SecretSnapshot())


@pytest.mark.parametrize("length", [230, 231, 232, 255, 256])
@pytest.mark.parametrize("multibyte", [False, True])
def test_safe_name_boundaries_are_idempotent(length, multibyte):
    name = "я" * (length // 2) + "a" * (length % 2) if multibyte else "a" * length
    assert len(name.encode()) == length
    allocated = artifact_name(name, set())
    if length <= 255:
        assert allocated == name
    else:
        assert len(allocated.encode()) <= 230
    assert artifact_name(allocated, set()) == allocated

    paths = PathNames(Workspace.parts)
    resolved = paths.resolve(f"parent/{name}/file")
    assert paths.resolve(resolved) == resolved
    assert paths.resolve(f"parent/{name}/file") == resolved
    for write in (False, True):
        fresh = PathNames(Workspace.parts)
        assert fresh.resolve(resolved, write=write) == resolved


@pytest.mark.parametrize("length", [230, 231, 232, 255, 256])
@pytest.mark.parametrize("multibyte", [False, True])
def test_collision_suffix_fits_and_survives_a_fresh_allocator(length, multibyte):
    name = "я" * (length // 2) + "a" * (length % 2) if multibyte else "a" * length
    used = set()
    first, second = artifact_name(name, used), artifact_name(name, used)
    assert first != second
    assert used == {first, second}
    assert len(second.encode()) == 255
    assert re.search(r"\.[0-9a-f]{24}$", second)
    assert artifact_name(second, set()) == second
    paths = PathNames(Workspace.parts)
    assert paths.resolve(paths.resolve(second)) == second
