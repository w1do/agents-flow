"""A deterministic agent with no API or third-party dependencies."""

from .check_results import finish_checks

STUB_FILE = "runner-stub.txt"
STUB_CONTENT = "Agents Flow stub implementation.\n"


def run(request, events):
    if request.stage == "planning":
        events.emit("plan", plan_text=(
            "1. Write runner-stub.txt inside the task worktree.\n"
            "2. Run the verification commands supplied by testing skills.\n"
            "3. Report the changed path and verification exit codes."
        ))
    elif request.stage == "implementation":
        request.workspace.write(STUB_FILE, STUB_CONTENT)
        checkpoint = dict(request.data.get("checkpoint") or {})
        checkpoint.update(stage=request.stage, changed_paths=[STUB_FILE])
        events.emit("progress", message="Stub file written", checkpoint=checkpoint)
        events.emit("result", result_summary="Stub implementation complete",
                    result_data={"changed_paths": [STUB_FILE]})
    else:
        finish_checks(request, events)
