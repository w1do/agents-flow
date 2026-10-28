import io
import shutil

import pytest

from runner.checks import run_checks
from runner.errors import RunnerError
from runner.protocol import Events, parse_json
from test_checks import request


def test_missing_bwrap_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    stream = io.StringIO()
    req = request(tmp_path, ("sh", "touch should-not-exist"))
    with pytest.raises(RunnerError, match="sandbox_unavailable"):
        run_checks(req, Events(stream))
    event = parse_json(stream.getvalue())
    assert event["code"] == "sandbox_unavailable"
    assert not (tmp_path / "should-not-exist").exists()


def test_unknown_language_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: "/bin/false")
    stream = io.StringIO()
    with pytest.raises(RunnerError, match="unsupported_language"):
        run_checks(request(tmp_path, ("ruby", "puts 'no'")), Events(stream))
    assert parse_json(stream.getvalue())["code"] == "unsupported_language"


def test_missing_bwrap_produces_terminal_failure(task_input, invoke, tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    task_input.update(stage="testing", read_only=False, skills=[
        {"category": "testing", "content": "```sh\ntouch must-not-run\n```"}])
    code, events = invoke(task_input)
    assert code == 1
    assert events[0]["code"] == "sandbox_unavailable"
    assert events[0]["exit_code"] == 127
    assert events[-1]["type"] == "failure"
    assert "sandbox_unavailable" in events[-1]["message"]
    assert not (tmp_path / "must-not-run").exists()


