import io
import os
import socket
import shutil
import threading
import time
from types import SimpleNamespace

import pytest

from runner.checks import run_checks
from runner.protocol import Events, parse_json
from runner.config import Config
from runner.workspace import Workspace


def request(tmp_path, content):
    return SimpleNamespace(
        workspace=Workspace(str(tmp_path)),
        skills=[{"content": f"{chr(96)*3}{content[0]}\n{content[1]}\n{chr(96)*3}"}],
        data={}, stage="testing",
    )


pytestmark = pytest.mark.usefixtures("requires_bwrap")


def execute(tmp_path, language, command):
    Config.from_env()
    stream = io.StringIO()
    req = request(tmp_path, (language, command))
    outcome = run_checks(req, Events(stream))
    return outcome, [parse_json(line) for line in stream.getvalue().splitlines()]


def test_bash_block_uses_bash_and_preserves_duplicate_commands(tmp_path):
    cmd = "items=(alpha beta); declare -p items | grep -q beta"
    req = SimpleNamespace(
        workspace=Workspace(str(tmp_path)),
        skills=[{"content": f"{chr(96)*3}bash\n{cmd}\n{chr(96)*3}"},
                {"content": f"{chr(96)*3}bash\n{cmd}\n{chr(96)*3}"}],
        data={}, stage="testing",
    )
    stream = io.StringIO()
    outcome = run_checks(req, Events(stream))
    events = [parse_json(line) for line in stream.getvalue().splitlines()]
    assert outcome == {"checks_run": 2, "checks_passed": True}
    assert [event["command"] for event in events if event["type"] == "test_result"] == [cmd, cmd]


def test_sandbox_blocks_writes_outside_worktree_and_home_is_private(tmp_path):
    command = 'printf bad >/etc/runner-sandbox-denied; printf bad >"$HOME/denied"'
    _, events = execute(tmp_path, "sh", command)
    assert events[0]["exit_code"] != 0
    assert not os.path.exists("/etc/runner-sandbox-denied")
    assert not (tmp_path / "denied").exists()


def test_sandbox_has_no_network(tmp_path):
    command = "import socket\nsocket.socket()"
    _, events = execute(tmp_path, "python3", command)
    assert events[0]["exit_code"] != 0


def test_sandbox_hides_host_home_run_and_unix_sockets(tmp_path):
    host_socket = f"/tmp/runner-host-socket-{os.getpid()}.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(host_socket)
    try:
        command = (f"test ! -e {host_socket} && test -d /home/runner && "
                   "test -z \"$(find /home -mindepth 1 -maxdepth 1 ! -name runner -print -quit)\" && "
                   "test -z \"$(find /run -mindepth 1 -print -quit)\"")
        _, events = execute(tmp_path, "sh", command)
        assert events[0]["exit_code"] == 0
    finally:
        listener.close()
        os.unlink(host_socket)


def test_sandbox_masks_sensitive_files_blocks_sockets_and_limits_etc(tmp_path):
    (tmp_path / ".env.local").write_text("private")
    (tmp_path / ".agent-token").write_text("private")
    command = ("test ! -s .env.local && test ! -s .agent-token && "
               "test ! -e /etc/ssh_config && "
               "if python3 -c 'import socket; socket.socket(socket.AF_UNIX)' >/dev/null 2>&1; "
               "then exit 1; fi")
    _, events = execute(tmp_path, "sh", command)
    assert events[0]["exit_code"] == 0


def test_shell_artifacts_are_redacted_before_collection(tmp_path, monkeypatch):
    secret = "shell-created-secret-917263"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    command = f"printf '%s' '{secret}' > result.txt"
    _, events = execute(tmp_path, "sh", command)
    assert events[0]["exit_code"] == 0
    assert secret.encode() not in (tmp_path / "result.txt").read_bytes()
    assert b"[REDACTED]" in (tmp_path / "result.txt").read_bytes()


def test_read_only_root_keeps_system_files_readable(tmp_path):
    _, events = execute(tmp_path, "sh", "test -s /etc/passwd")
    assert events[0]["exit_code"] == 0


def test_timeout_kills_process_group(tmp_path, monkeypatch):
    import runner.checks as checks

    monkeypatch.setattr(checks, "TIMEOUT", 0.1)
    monkeypatch.setattr(checks, "TERMINATE_GRACE", 0.1)
    original_popen = checks.subprocess.Popen
    process_ids = {}

    def capture_process(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        process_ids["pgid"] = process.pid
        return process

    monkeypatch.setattr(checks.subprocess, "Popen", capture_process)
    finished = threading.Event()
    result = {}

    def run_check():
        try:
            result["value"] = execute(
                tmp_path,
                "bash",
                "trap '' TERM; echo $BASHPID > child.pid; exec tail -f /dev/null & wait",
            )
        except BaseException as exc:
            result["error"] = exc
        finally:
            finished.set()

    worker = threading.Thread(target=run_check)
    worker.start()
    ready = tmp_path / "child.pid"
    deadline = time.monotonic() + 2
    while not ready.exists() and time.monotonic() < deadline:
        finished.wait(min(0.01, max(0, deadline - time.monotonic())))
    assert ready.exists(), "child did not report readiness before timeout"
    assert finished.wait(3), "timed-out command cleanup did not finish"
    worker.join()
    assert "error" not in result
    _, events = result["value"]
    assert events[0]["exit_code"] == 124
    assert int(ready.read_text()) > 0
    with pytest.raises(ProcessLookupError):
        os.killpg(process_ids["pgid"], 0)
