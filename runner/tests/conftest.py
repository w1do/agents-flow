import io
import json
import socket
import shutil
import subprocess

import pytest

from runner.cli import main


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "stub")

    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def task_input(tmp_path):
    for args in (("init", "-b", "task/task-9"), ("config", "user.name", "Runner Test"),
                 ("config", "user.email", "runner@example.invalid"),
                 ("commit", "--allow-empty", "-m", "base")):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    return {
        "task": {"id": "task-9", "title": "Implement task", "description": "Do the work"},
        "stage": "planning", "path": str(tmp_path), "worktree": str(tmp_path),
        "branch": "task/task-9", "read_only": True, "checkpoint": None, "skills": [],
    }


@pytest.fixture
def invoke():
    def run(data):
        output = io.StringIO()
        code = main([], stdin=io.StringIO(json.dumps(data)), stdout=output)
        return code, [json.loads(line) for line in output.getvalue().splitlines()]

    return run


@pytest.fixture
def requires_bwrap():
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap is unavailable")
