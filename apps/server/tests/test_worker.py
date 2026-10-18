"""Сценарий 3.2: worker работает в цикле и завершается с кодом 0 по SIGTERM."""

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest


def test_worker_stops_cleanly_on_sigterm(
    valid_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SEC", "0.2")
    # Консольный скрипт лежит рядом с интерпретатором venv; так тест не зависит от uv.
    script = Path(sys.executable).parent / "harness-server"

    process = subprocess.Popen(
        [str(script), "worker"],
        cwd=tmp_path,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stderr is not None
        # Ждём строку запуска: до этого момента обработчики сигналов ещё не установлены.
        for line in process.stderr:
            if "worker started" in line:
                break
        else:
            pytest.fail("worker не запустился")

        process.send_signal(signal.SIGTERM)
        exit_code = process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    assert exit_code == 0
