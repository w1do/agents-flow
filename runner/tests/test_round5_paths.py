"""Shell delimiters and protected names cannot bypass the .key exception."""
import io
import json

import pytest

from runner.protocol import Events
from runner.redaction import redact, safe_command


@pytest.mark.parametrize("command,expected", [
    ("cat key.PEM&&echo ok", "cat [REDACTED]&&echo ok"),
    ("cat .NPMRC&echo ok", "cat [REDACTED]&echo ok"),
])
def test_shell_separator_pocs_are_redacted(command, expected):
    assert redact(command) == expected
    assert safe_command(command) == "[REDACTED]"


@pytest.mark.parametrize("separator", ["&", "&&", "|", "||", ";", ">", ">>", "<", " 2>"])
@pytest.mark.parametrize("path", ["key.PEM", ".NPMRC", '"key.PEM"', "'.NPMRC'"])
def test_shell_operators_delimit_protected_paths(separator, path):
    command = f"cat {path}{separator}echo ok"
    assert "[REDACTED]" in redact(command)
    assert safe_command(command) == "[REDACTED]"


@pytest.mark.parametrize("separator", ["&", "&&", "|", "||"])
def test_query_prefix_cannot_hide_later_shell_word(separator):
    command = f"cat harmless?x=1{separator}key.PEM"
    assert redact(command) == "cat [REDACTED]"
    assert safe_command(command) == "[REDACTED]"


@pytest.mark.parametrize("text", ['echo "left&&right"', "echo 'left&&right'",
                                   'const text = "left&&right";',
                                   "const ok = event.key && ready;",
                                   'echo "event.key&&ready"'])
def test_quoted_and_programming_ampersands_remain_unchanged(text):
    assert redact(text) == text
    assert safe_command(text) == text


@pytest.mark.parametrize("text", ["id_rsa.key", "id_rsa.key?marker=42",
                                   "event.key?marker=42", "event.key#marker=42",
                                   "obj.id_rsa.key", "obj.PEM.key"])
def test_key_exception_cannot_hide_protected_names_or_tails(text):
    assert redact(text) == "[REDACTED]"
    assert safe_command(text) == "[REDACTED]"


@pytest.mark.parametrize("text", ["id_rsa.key", "id_rsa.key?marker=42", "cat .NPMRC&echo ok"])
def test_protected_values_are_masked_in_ndjson(text):
    output = io.StringIO()
    Events(output).emit("progress", message=text, payload={text: text})
    event = json.loads(output.getvalue())
    assert text not in output.getvalue()
    assert "marker=42" not in output.getvalue()
    assert "[REDACTED]" in event["message"]
    assert "[REDACTED]" in next(iter(event["payload"]))
