import base64
import json
from urllib.parse import quote

import pytest

from runner.config import Config
from runner.redaction import redact, redact_bytes


def test_single_env_file_read_supplies_key_and_snapshot(tmp_path, monkeypatch):
    from runner.envfile import read_env_file

    path = tmp_path / "runner.env"
    path.write_text("OPENAI_API_KEY=first-generation\nAGENT_MODEL=offline\n")
    path.chmod(0o600)
    calls = []

    def rotating(env):
        result = read_env_file(env)
        calls.append(result)
        path.write_text("OPENAI_API_KEY=second-generation\nAGENT_MODEL=offline\n")
        return result

    monkeypatch.setattr("runner.config.read_env_file", rotating)
    env = {"AGENT_PROVIDER": "deepagents", "AGENT_FLOW_RUNNER_ENV_FILE": str(path)}
    config = Config.from_env(env)
    assert len(calls) == 1
    assert config.api_key == "first-generation"
    assert config.api_key in config.secrets.values
    assert redact(config.api_key) == "[REDACTED]"
    path.unlink()
    assert redact(config.api_key) == "[REDACTED]"
    assert len(calls) == 1


def test_rotation_is_explicit_and_previous_snapshot_is_immutable(tmp_path):
    path = tmp_path / "runner.env"
    path.write_text("OPENAI_API_KEY=reload-old-key\nAGENT_MODEL=offline\n")
    path.chmod(0o600)
    env = {"AGENT_PROVIDER": "deepagents", "AGENT_FLOW_RUNNER_ENV_FILE": str(path)}
    first = Config.from_env(env)
    path.write_text("OPENAI_API_KEY=reload-new-key\nAGENT_MODEL=offline\n")
    assert first.api_key == "reload-old-key"
    assert "reload-new-key" not in first.secrets.values
    second = first.reload(env)
    assert second.api_key == "reload-new-key"
    assert redact([first.api_key, second.api_key]) == ["[REDACTED]", "[REDACTED]"]


SECRET = "case/Sensitive+credential?55891"
REPRESENTATIONS = [
    SECRET, f'"{SECRET}"', f"'{SECRET}'",
    base64.b64encode(SECRET.encode()).decode(),
    base64.b64encode(SECRET.encode()).decode().rstrip("="),
    base64.urlsafe_b64encode(SECRET.encode()).decode(),
    base64.urlsafe_b64encode(SECRET.encode()).decode().rstrip("="),
    quote(SECRET, safe="").replace("%2F", "%2f").replace("%2B", "%2b").replace("%3F", "%3f"),
    SECRET.encode().hex(), SECRET.encode().hex().upper(),
    "".join(f"\\u{ord(c):04x}" for c in SECRET),
]


@pytest.mark.parametrize("encoded", REPRESENTATIONS)
def test_same_normalizer_covers_values_names_and_binary(encoded):
    Config.from_env({"SERVICE_KEY": f"  '{SECRET}'  "})
    result = redact({f"file-{encoded}": [encoded]})
    assert encoded not in json.dumps(result)
    for codec in ("utf-8", "utf-16-le", "utf-16-be"):
        raw = f"prefix {encoded} suffix".encode(codec)
        cleaned = redact_bytes(raw)
        assert encoded.encode(codec) not in cleaned
        assert "[REDACTED]" in cleaned.decode(codec)


def test_embedded_unicode_escape_inside_a_string():
    Config.from_env({"SERVICE_KEY": SECRET})
    encoded = "".join(f"\\u{ord(c):04x}" for c in SECRET)
    assert redact(f'JSON string: "x {encoded} y"') == 'JSON string: "x [REDACTED] y"'


def test_utf16_with_bom_is_still_valid_text():
    Config.from_env({"SERVICE_KEY": SECRET})
    raw = f"prefix {SECRET} suffix".encode("utf-16")
    assert redact_bytes(raw).decode("utf-16") == "prefix [REDACTED] suffix"
