import io
import json

import pytest

from runner.cli import main
from runner.config import Config
from runner.errors import RunnerError
from runner.protocol import Events, Request, dump_json, parse_json


def test_harness_planning_contract(task_input, invoke):
    code, events = invoke(task_input)
    assert code == 0
    assert [e["type"] for e in events] == ["plan"]
    assert events[0]["plan_text"].strip()


@pytest.mark.parametrize("raw", ["", "[]", "{} {}", '{"stage":"planning","stage":"testing"}',
                                 '{"stage":"planning","checkpoint":NaN}',
                                 '{"stage":"planning","checkpoint":{"number":1e999}}'])
def test_bad_json_produces_only_failure(raw):
    stream = io.StringIO()
    assert main([], stdin=io.StringIO(raw), stdout=stream) == 1
    assert json.loads(stream.getvalue())["type"] == "failure"


@pytest.mark.parametrize("field,value", [
    ("stage", "unknown"), ("task", None), ("checkpoint", []), ("skills", {}),
    ("read_only", "true"), ("read_only", False), ("result_data", "bad"),
    ("path", "/missing/runner/worktree"), ("worktree", "."),
])
def test_invalid_input_is_failure(task_input, invoke, field, value):
    task_input[field] = value
    code, events = invoke(task_input)
    assert code == 1
    assert [e["type"] for e in events] == ["failure"]


def test_checkpoint_and_harness_fields_pass_through(task_input):
    checkpoint = {"cursor": "resume", "integer": 9007199254740993}
    task_input.update(checkpoint=checkpoint, plan_text="Approved", feedback="Revise")
    request = Request.read(io.StringIO(json.dumps(task_input)))
    assert request.data["checkpoint"] == checkpoint
    assert request.data["plan_text"] == "Approved"
    assert request.data["feedback"] == "Revise"


def test_events_are_bounded_flushed_ndjson():
    output = io.StringIO()
    events = Events(output)
    events.emit("progress", message="working", payload={"step": 1}, checkpoint={"cursor": "saved"})
    events.emit("result", result_summary="Done", result_data={"changed_paths": ["file"]})
    assert len(output.getvalue().splitlines()) == 2
    assert events.checkpoint == {"cursor": "saved"}
    with pytest.raises(RunnerError, match="sequence"):
        events.emit("result")


def test_oversized_event_does_not_write():
    output = io.StringIO()
    with pytest.raises(RunnerError, match="1 MiB"):
        Events(output).emit("plan", plan_text="x" * (1024 * 1024))
    assert output.getvalue() == ""


def test_oversized_input_checkpoint_cannot_break_failure_protocol(task_input, invoke):
    task_input.update(stage="implementation", read_only=True,
                      checkpoint={"large": "x" * (1024 * 1024)})
    code, events = invoke(task_input)
    assert code == 1
    assert events == [{"type": "failure", "message": "Stage is read-only"}]


def test_credentials_never_reach_events(monkeypatch):
    secret = "private-runtime-credential"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    Config.from_env()
    stream = io.StringIO()
    Events(stream).emit("progress", message=f"value={secret}", checkpoint={"api_key": secret})
    assert secret not in stream.getvalue()
    assert "[REDACTED]" in stream.getvalue()


def test_redacts_literal_base64_and_bearer_values(monkeypatch):
    import base64

    secret = "known-runtime-secret"
    monkeypatch.setenv("SERVICE_KEY", secret)
    Config.from_env()
    command = f"export SERVICE_KEY={secret}; echo {base64.b64encode(secret.encode()).decode()}; Authorization: Bearer {secret}"
    output = io.StringIO()
    Events(output).emit("test_result", command=command, exit_code=0, summary="passed")
    assert secret not in output.getvalue()
    assert base64.b64encode(secret.encode()).decode() not in output.getvalue()
    assert "Bearer [REDACTED]" in output.getvalue()
    assert "SERVICE_KEY=[REDACTED]" in output.getvalue()


def test_json_numbers_round_trip_without_precision_loss():
    number = 9007199254740993
    parsed = parse_json('{"integer":9007199254740993,"fraction":1.25}')
    assert parsed["integer"] == number
    assert dump_json(parsed) == '{"integer": 9007199254740993, "fraction": 1.25}'
    output = io.StringIO()
    Events(output).emit("result", result_data=parsed)
    assert '"integer": 9007199254740993' in output.getvalue()
    assert parse_json(output.getvalue())["result_data"] == parsed


def test_decimal_serialization_preserves_user_marker_like_key_and_text():
    value = {"n": parse_json("1.25"), "__RUNNER_DECIMAL_0__": "text"}
    output = io.StringIO()
    Events(output).emit("result", result_data=value)
    assert parse_json(output.getvalue())["result_data"] == value


@pytest.mark.parametrize("stage,skill", [
    ("planning", {"filename": "git--publish.md", "content": "Publish"}),
    ("implementation", {"category": "Деплой", "content": "Deploy"}),
    ("testing", {"category": "development", "content": "Code"}),
    ("publication", {"category": "testing", "content": "Tests"}),
])
def test_stage_skill_isolation(task_input, invoke, stage, skill):
    task_input.update(stage=stage, read_only=stage == "planning", skills=[skill])
    code, events = invoke(task_input)
    assert code == 1
    assert events[-1]["type"] == "failure"


@pytest.mark.usefixtures("requires_bwrap")
def test_publication_result_requires_success_and_message(task_input, invoke):
    task_input.update(stage="publication", read_only=False, skills=[
        {"category": "git", "allowed_paths": ["published.txt"],
         "content": "```sh\nprintf published > published.txt\n```"}])
    code, events = invoke(task_input)
    assert code == 0
    terminal = events[-1]
    assert terminal["type"] == "result"
    assert terminal["success"] is True
    assert terminal["message"]
