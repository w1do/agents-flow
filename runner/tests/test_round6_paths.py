"""Escapes, quote concatenation and punctuation share one masking policy."""
import io
import json

import pytest

from runner.protocol import Events
from runner.redaction import redact, safe_command

POCS = [r"cat .NPM\RC", r"cat key.PE\M", "cat key.PE''M", 'cat key.PE"M"',
        r"cat key.PEM\&echo ok", "cat key.PEM\\\n;echo", "cat key.PE\\\nM",
        'echo "Use .NPMRC please."', 'echo "file=.NPMRC:fixture"']
BENIGN = ["event.key", "KeyboardEvent.key", "Use event.key.", "Use KeyboardEvent.key!",
          "echo left&&right", 'const text = "left&right";', '<a href="/?a=1&b=2">',
          "const ok = event.key && ready;", 'echo "event.key&&ready"']


@pytest.mark.parametrize("text", POCS)
def test_shell_normalized_names_are_masked_in_commands_and_ndjson(text):
    assert "[REDACTED]" in redact(text)
    assert safe_command(text) == "[REDACTED]"
    output = io.StringIO()
    Events(output).emit("progress", message=text, payload={text: text})
    event = json.loads(output.getvalue())
    assert "[REDACTED]" in event["message"]
    assert "[REDACTED]" in next(iter(event["payload"]))
    assert "[REDACTED]" in next(iter(event["payload"].values()))
    assert text not in event["message"]


@pytest.mark.parametrize("text", BENIGN)
def test_benign_identifiers_punctuation_and_ampersands_are_preserved(text):
    assert redact(text) == text
    assert safe_command(text) == text


@pytest.mark.parametrize("text", ["key.PEM!", ".NPMRC.", "id_rsa.key!",
                                   "obj.PEM.key.", "event.key?marker=42!"])
def test_punctuation_does_not_weaken_protected_path_masking(text):
    assert redact(text) == "[REDACTED]"


def test_quoted_json_value_retains_its_delimiters():
    text = json.dumps({"path": ".env.local", "content": "ordinary"})
    assert json.loads(redact(text)) == {"path": "[REDACTED]", "content": "ordinary"}
