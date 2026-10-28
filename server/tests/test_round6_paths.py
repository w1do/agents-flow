"""Report masking normalizes escaped and concatenated shell path names."""
import json

import pytest

from app.services.skill_content import redact, sanitize

POCS = [r"cat .NPM\RC", r"cat key.PE\M", "cat key.PE''M", 'cat key.PE"M"',
        r"cat key.PEM\&echo ok", "cat key.PEM\\\n;echo", "cat key.PE\\\nM",
        'echo "Use .NPMRC please."', 'echo "file=.NPMRC:fixture"']
BENIGN = ["event.key", "KeyboardEvent.key", "Use event.key.", "Use KeyboardEvent.key!",
          "echo left&&right", 'const text = "left&right";', '<a href="/?a=1&b=2">',
          "const ok = event.key && ready;", 'echo "event.key&&ready"']


@pytest.mark.parametrize("text", POCS)
def test_shell_normalized_names_are_masked_in_report_values_and_keys(text):
    expected = redact(text)
    assert "[REDACTED]" in expected and text not in expected
    assert sanitize({text: [text]}) == {expected: [expected]}


@pytest.mark.parametrize("text", BENIGN)
def test_benign_identifiers_punctuation_and_ampersands_are_preserved(text):
    assert redact(text) == text
    assert sanitize({text: text}) == {text: text}


@pytest.mark.parametrize("text", ["key.PEM!", ".NPMRC.", "id_rsa.key!",
                                   "obj.PEM.key.", "event.key?marker=42!"])
def test_punctuation_does_not_weaken_protected_path_masking(text):
    assert redact(text) == "[REDACTED]"


def test_quoted_json_value_retains_its_delimiters():
    text = json.dumps({"path": ".env.local", "content": "ordinary"})
    assert json.loads(redact(text)) == {"path": "[REDACTED]", "content": "ordinary"}
