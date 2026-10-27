from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.task_status import STATUSES, transition, validate_transition


EXPECTED = {
    "new": {"choosing", "paused", "trash"},
    "choosing": {"planning", "paused", "trash", "error", "stalled"},
    "planning": {"backlog", "paused", "trash", "error", "stalled"},
    "backlog": {"active", "planning", "paused", "trash", "error", "stalled"},
    "active": {"testing", "paused", "trash", "error", "stalled"},
    "testing": {"ready", "paused", "trash", "error", "stalled"},
    "ready": {"merged", "active", "ready", "paused", "trash", "error", "stalled"},
    "merged": {"trash"}, "error": {"trash"}, "stalled": {"new", "trash"},
    "paused": {"trash"}, "trash": {"trash"},
}


@pytest.mark.parametrize("current", sorted(STATUSES))
@pytest.mark.parametrize("target", sorted(STATUSES))
def test_transition_matrix(current, target):
    if target in EXPECTED[current]:
        validate_transition(current, target, "admin")
    else:
        with pytest.raises(HTTPException) as error:
            validate_transition(current, target, "admin")
        assert error.value.status_code == 409


def test_main_lifecycle_and_forbidden_backlog_merge():
    task = SimpleNamespace(status="new")
    for target in ("choosing", "planning", "backlog"):
        transition(task, target)
    with pytest.raises(HTTPException) as error:
        transition(task, "merged")
    assert error.value.status_code == 409
    assert task.status == "backlog"
    for target in ("active", "testing", "ready", "merged"):
        transition(task, target)
    assert task.status == "merged"


@pytest.mark.parametrize("target,status", [
    ("merged", 403), ("active", 403), ("trash", 403), ("paused", 403), ("new", 409),
])
def test_agent_cannot_make_admin_transition(target, status):
    with pytest.raises(HTTPException) as error:
        validate_transition("ready", target, "agent")
    assert error.value.status_code == status


def test_only_admin_restarts_stalled():
    with pytest.raises(HTTPException) as error:
        validate_transition("stalled", "new")
    assert error.value.status_code == 403
    validate_transition("stalled", "new", "admin")
    with pytest.raises(HTTPException):
        validate_transition("unknown", "new")
