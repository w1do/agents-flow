"""Report text and event IDs share the protected-path rules."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.reports import Report
from app.services.skill_content import redact, sanitize


@pytest.mark.parametrize("command,expected", [
    ("cat key.PEM&&echo ok", "cat [REDACTED]&&echo ok"),
    ("cat .NPMRC&echo ok", "cat [REDACTED]&echo ok"),
])
def test_shell_separator_pocs_are_redacted(command, expected):
    assert redact(command) == expected
    assert sanitize({command: command}) == {expected: expected}


@pytest.mark.parametrize("separator", ["&", "&&", "|", "||", ";", ">", ">>", "<", " 2>"])
@pytest.mark.parametrize("path", ["key.PEM", ".NPMRC", '"key.PEM"', "'.NPMRC'"])
def test_shell_operators_delimit_protected_paths(separator, path):
    command = f"cat {path}{separator}echo ok"
    assert "[REDACTED]" in redact(command)
    assert sanitize(command) == redact(command)


@pytest.mark.parametrize("separator", ["&", "&&", "|", "||"])
def test_query_prefix_cannot_hide_later_shell_word(separator):
    command = f"cat harmless?x=1{separator}key.PEM"
    assert redact(command) == "cat [REDACTED]"
    assert sanitize(command) == "cat [REDACTED]"


@pytest.mark.parametrize("text", ['echo "left&&right"', "echo 'left&&right'",
                                   'const text = "left&&right";',
                                   "const ok = event.key && ready;",
                                   'echo "event.key&&ready"'])
def test_quoted_and_programming_ampersands_remain_unchanged(text):
    assert redact(text) == text
    assert sanitize(text) == text


@pytest.mark.parametrize("text", ["id_rsa.key", "id_rsa.key?marker=42",
                                   "event.key?marker=42", "event.key#marker=42",
                                   "obj.id_rsa.key", "obj.PEM.key"])
def test_key_exception_cannot_hide_protected_names_or_tails(text):
    assert redact(text) == "[REDACTED]"
    assert sanitize({text: text}) == {"[REDACTED]": "[REDACTED]"}


@pytest.mark.parametrize("event_id", ["id_rsa.key", "obj.id_rsa.key", "obj.PEM.key"])
def test_protected_member_event_id_is_rejected(event_id):
    with pytest.raises(ValidationError):
        Report(lease_id=uuid4(), event_id=event_id)


@pytest.mark.parametrize("event_id", ["event.key", "KeyboardEvent.key"])
def test_benign_member_event_id_is_accepted(event_id):
    assert Report(lease_id=uuid4(), event_id=event_id).event_id == event_id


async def test_protected_member_event_id_returns_sanitized_422(flow):
    task = flow.task("testing", leased=True)
    response = await flow.report(task, "events", {"event_type": "progress", "message": "ok"},
                                 event_id="id_rsa.key")
    assert response.status_code == 422
    assert "id_rsa" not in response.text
