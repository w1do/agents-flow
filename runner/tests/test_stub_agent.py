from pathlib import Path

import pytest

from runner.stub import STUB_CONTENT, STUB_FILE


def implementation(task_input):
    return dict(task_input, stage="implementation", read_only=False, plan_text="Approved plan")


def checking_input(task_input, command):
    return dict(task_input, stage="testing", read_only=False, skills=[
        {"category": "testing", "filename": "testing--check.md",
         "content": f"Verify the project:\n```sh\n{command}\n```"}])


def test_planning_is_deterministic_and_does_not_write(task_input, invoke):
    before = list(Path(task_input["worktree"]).iterdir())
    first = invoke(task_input)
    assert first == invoke(task_input)
    assert list(Path(task_input["worktree"]).iterdir()) == before


def test_implementation_writes_only_inside_worktree(task_input, invoke, tmp_path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    original = tmp_path / "main.txt"
    original.write_text("unchanged")
    request = implementation(dict(task_input, path=str(worktree), worktree=str(worktree)))
    code, events = invoke(request)
    assert code == 0
    assert (worktree / STUB_FILE).read_text() == STUB_CONTENT
    assert original.read_text() == "unchanged"
    assert [e["type"] for e in events] == ["progress", "result"]
    assert events[-1]["result_data"]["changed_paths"] == [STUB_FILE]
    request["checkpoint"] = events[0]["checkpoint"]
    assert invoke(request) == (code, events)


@pytest.mark.usefixtures("requires_bwrap")
def test_testing_runs_real_skill_command_and_preserves_previous_result(task_input, invoke, tmp_path):
    assert invoke(implementation(task_input))[0] == 0
    command = f'test -f {STUB_FILE}\nprintf checked > proof.txt'
    request = checking_input(task_input, command)
    request["result_data"] = {"changed_paths": [STUB_FILE], "implementation": "kept"}
    code, events = invoke(request)
    assert code == 0
    assert (tmp_path / "proof.txt").read_text() == "checked"
    report = events[0]
    assert report == {"type": "test_result", "command": command, "exit_code": 0, "summary": "passed"}
    data = events[-1]["result_data"]
    assert data["changed_paths"] == ["proof.txt", STUB_FILE]
    assert data["implementation"] == "kept"
    assert data["checks_run"] == 1 and data["checks_passed"] is True
    assert data["verification"]["head_sha"] == data["base_sha"]
    assert data["verification"]["worktree_clean"] is False


@pytest.mark.usefixtures("requires_bwrap")
def test_failed_check_is_reported_before_failure_and_preserves_checkpoint(task_input, invoke):
    request = checking_input(task_input, "exit 7")
    request["checkpoint"] = {"cursor": "saved"}
    code, events = invoke(request)
    assert code == 1
    assert [e["type"] for e in events] == ["test_result", "progress", "failure"]
    assert events[0]["exit_code"] == 7
    assert events[-1]["checkpoint"]["cursor"] == "saved"
    assert events[-1]["checkpoint"]["checks_completed"] == 1


@pytest.mark.usefixtures("requires_bwrap")
def test_project_command_does_not_receive_credentials(task_input, invoke, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-runtime-key")
    monkeypatch.setenv("AGENTS_FLOW_AGENT_TOKEN", "private-agent-token")
    command = 'test -z "${OPENAI_API_KEY-}"\ntest -z "${AGENTS_FLOW_AGENT_TOKEN-}"'
    code, events = invoke(checking_input(task_input, command))
    assert code == 0
    assert events[0]["exit_code"] == 0


@pytest.mark.usefixtures("requires_bwrap")
def test_check_output_is_not_logged(task_input, invoke, capsys):
    code, events = invoke(checking_input(task_input, "printf hidden-secret\nprintf hidden-secret >&2"))
    assert code == 0
    assert "hidden-secret" not in str([{k: v for k, v in e.items() if k != "command"} for e in events])
    assert capsys.readouterr() == ("", "")


def test_read_only_implementation_is_rejected(task_input, invoke, tmp_path):
    request = implementation(task_input)
    request["read_only"] = True
    code, events = invoke(request)
    assert code == 1
    assert events[-1]["type"] == "failure"
    assert not (tmp_path / STUB_FILE).exists()


@pytest.mark.parametrize("command,success", [("exit 0", True), ("exit 5", False)])
@pytest.mark.usefixtures("requires_bwrap")
def test_publication_reports_outcome(task_input, invoke, command, success):
    request = dict(task_input, stage="publication", read_only=False, skills=[
        {"category": "git", "content": f"```sh\n{command}\n```"}])
    code, events = invoke(request)
    assert code == 0
    assert events[-1]["success"] is success


def test_no_publication_commands_cannot_claim_success(task_input, invoke):
    code, events = invoke(dict(task_input, stage="publication", read_only=False))
    assert code == 0
    assert events[-1]["success"] is False
