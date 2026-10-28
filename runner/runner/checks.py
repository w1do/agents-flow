"""Run inline skill programs in a fail-closed bubblewrap namespace."""

import os
import shutil
import signal
import subprocess
import time

from .errors import RunnerError
from .redaction import redact, safe_command
from .skills import commands
from .sandbox import sandbox_args
from .sandbox_paths import projected_worktree

TIMEOUT = 300
TERMINATE_GRACE = 2
GROUP_EXIT_TIMEOUT = 2
GROUP_POLL_INTERVAL = 0.01


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def _wait_for_group_exit(pgid, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(GROUP_POLL_INTERVAL)


def _kill_process_group(process):
    pgid = process.pid
    _signal_group(pgid, signal.SIGTERM)
    _wait_for_group_exit(pgid, TERMINATE_GRACE)
    _signal_group(pgid, signal.SIGKILL)
    leader_exited = True
    try:
        process.wait(timeout=GROUP_EXIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        leader_exited = False
    if not _wait_for_group_exit(pgid, GROUP_EXIT_TIMEOUT):
        raise RunnerError("process_group_cleanup_timeout")
    if not leader_exited:
        try:
            process.wait(timeout=GROUP_EXIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise RunnerError("process_cleanup_timeout") from None


def program(language, command):
    if language in {"", "sh"}:
        return ["/bin/sh", "-eu", "-c", command]
    if language == "bash":
        return ["/bin/bash", "-eu", "-c", command]
    if language in {"python", "python3"}:
        return ["python3", "-c", command]
    raise RunnerError("unsupported_language")


def run_one(request, events, bwrap, language, command, projected_fd):
    try:
        argv = program(language, command)
    except RunnerError:
        events.emit("test_result", command=safe_command(command), exit_code=126,
                    code="unsupported_language", summary=f"Unsupported skill language: {language or '(empty)'}")
        raise RunnerError(f"unsupported_language: {language or '(empty)'}") from None
    env = {k: os.environ[k] for k in ("PATH", "LANG", "TZ", "TERM") if k in os.environ}
    env.update(HOME="/home/runner", PYTHONDONTWRITEBYTECODE="1")
    try:
        sandbox, sandbox_fds = sandbox_args(request.workspace.root, projected_fd)
        try:
            process = subprocess.Popen(
                [bwrap, *sandbox, "--chdir", str(request.workspace.root), "--", *argv],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, pass_fds=sandbox_fds,
            )
        finally:
            for sandbox_fd in sandbox_fds:
                os.close(sandbox_fd)
    except OSError:
        raise RunnerError("Could not start isolated skill command") from None
    try:
        code = process.wait(timeout=TIMEOUT)
        summary = "passed" if code == 0 else "failed"
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        code, summary = 124, f"timed out after {TIMEOUT} seconds"
    events.emit("test_result", command=safe_command(command), exit_code=code, summary=redact(summary))
    return code


def run_checks(request, events):
    selected = commands(request.skills)
    if request.workspace.read_only and selected:
        raise RunnerError("Cannot run commands in a read-only stage")
    bwrap = shutil.which("bwrap")
    if selected and not bwrap:
        language, command = selected[0]
        events.emit("test_result", command=safe_command(command), exit_code=127, code="sandbox_unavailable",
                    summary="bubblewrap (bwrap) is required; skill command was not run")
        raise RunnerError("sandbox_unavailable: install bubblewrap to run skill commands")
    passed = True
    for index, (language, command) in enumerate(selected):
        with projected_worktree(request.workspace) as projected_fd:
            code = run_one(request, events, bwrap, language, command, projected_fd)
        passed = passed and code == 0
        checkpoint = dict(events.checkpoint or request.data.get("checkpoint") or {})
        checkpoint.update(stage=request.stage, checks_completed=index + 1)
        events.emit("progress", message="Skill command completed", checkpoint=checkpoint)
    return {"checks_run": len(selected), "checks_passed": passed}
