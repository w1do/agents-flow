"""Сценарии platform-config: глобальный harness.yaml без проектов, секреты и старая форма (D-65)."""

import json
from pathlib import Path

import pytest
from harness_server.config import ConfigError, load_config

EXAMPLE_CONFIG = Path(__file__).resolve().parents[3] / "config" / "harness.example.yaml"
# Фиктивный sha для тестов (D-51): настоящий закреплённый коммит — только в harness.yaml и D-51.
MEMORY_REF = "0123456789abcdef0123456789abcdef01234567"

SANDBOX = """\
sandbox:
  provider_id: sbx-1
"""


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "harness.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_example_config_is_valid() -> None:
    config = load_config(EXAMPLE_CONFIG)

    assert config.sandbox.provider_id == "local"
    assert config.sandbox.git_author.name == "agents-flow"


def test_config_without_workspaces_loads(tmp_path: Path) -> None:
    # Новая форма: проекты на сервере, в файле только сервер и песочница (D-65).
    config = load_config(_write(tmp_path, SANDBOX))

    assert config.sandbox.provider_id == "sbx-1"


@pytest.mark.parametrize("block", ["workspaces", "gitlab"])
def test_legacy_blocks_are_rejected_with_hint(tmp_path: Path, block: str) -> None:
    # Старая форма не запускает сервер: ConfigError называет блок и место, куда его перенести.
    body = f"{block}:\n  - id: demo\n" + SANDBOX

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    message = str(info.value)
    assert f"{block}" in message
    if block == "workspaces":
        assert "/api/console/projects" in message
    else:
        assert "секция gitlab удалена" in message


def test_secret_field_is_rejected_with_path(tmp_path: Path) -> None:
    body = SANDBOX + "  gitlab_token: glpat-leaked-value\n"

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    message = str(info.value)
    assert "sandbox.gitlab_token" in message
    assert "glpat-leaked-value" not in message


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "api_key",
        "Secret",
        "x-apikey",
        "accessToken",
        "clientSecret",
        "privateKey",
        "apiKey",
        "tokens",
        "secrets",
        "passwd",
        "pwd",
        "credential",
        "credentials",
    ],
)
def test_secret_like_keys_rejected_on_any_level(tmp_path: Path, key: str) -> None:
    body = SANDBOX + f"extra:\n  nested:\n    {key}: value-should-not-appear\n"

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "value-should-not-appear" not in str(info.value)
    assert f"extra.nested.{key}" in str(info.value)


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, SANDBOX + "unexpected: 1\n"))

    assert "unexpected" in str(info.value)


def test_missing_file_is_reported_with_path(tmp_path: Path) -> None:
    missing = tmp_path / "absent.yaml"

    with pytest.raises(ConfigError) as info:
        load_config(missing)

    assert str(missing) in str(info.value)


def test_binary_file_is_rejected_without_content(tmp_path: Path) -> None:
    path = tmp_path / "harness.yaml"
    path.write_bytes(b"\xff\xfe\x00\x81\x80 binary-marker")

    with pytest.raises(ConfigError) as info:
        load_config(path)

    message = str(info.value)
    assert str(path) in message
    assert "binary-marker" not in message


def test_empty_document_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, ""))


@pytest.mark.parametrize("field", ["claude_code_version", "openspec_version"])
def test_removed_sandbox_fields_are_actionable(tmp_path: Path, field: str) -> None:
    body = f"sandbox:\n  provider_id: sbx-1\n  {field}: old\n"
    with pytest.raises(ConfigError, match=field):
        load_config(_write(tmp_path, body))


def _memory_body(memory_lines: str) -> str:
    return "sandbox:\n  provider_id: sbx-1\n  memory:\n" + memory_lines


def test_memory_block_is_optional_and_parsed(tmp_path: Path) -> None:
    plain = load_config(_write(tmp_path, SANDBOX))
    assert plain.sandbox.memory is None
    config = load_config(
        _write(tmp_path, _memory_body("    embedding_ref: vault:demo/polza/embeddings\n"))
    )
    assert config.sandbox.memory is not None
    assert config.sandbox.memory.embedding_ref == "vault:demo/polza/embeddings"


@pytest.mark.parametrize("field", ["repo", "ref"])
def test_removed_memory_fields_are_actionable(tmp_path: Path, field: str) -> None:
    with pytest.raises(ConfigError, match=field):
        load_config(_write(tmp_path, _memory_body(f"    {field}: old\n")))


def test_memory_embedding_ref_must_be_vault_reference(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, _memory_body("    embedding_ref: sk-plain-key-value\n")))
    assert "sk-plain-key-value" not in str(info.value)


def test_git_author_defaults_when_block_absent(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, SANDBOX))

    assert config.sandbox.git_author.name == "agents-flow"
    assert config.sandbox.git_author.email == "agents-flow@noreply.local"


def test_git_author_custom_values_accepted(tmp_path: Path) -> None:
    body = (
        "sandbox:\n  provider_id: sbx-1\n  git_author:\n    name: Agent Bot\n"
        "    email: bot@example.com\n"
    )

    config = load_config(_write(tmp_path, body))

    assert config.sandbox.git_author.name == "Agent Bot"
    assert config.sandbox.git_author.email == "bot@example.com"


@pytest.mark.parametrize("name", ["   ", "a\nb", "x" * 101])
def test_git_author_name_rejected_when_blank_control_or_long(tmp_path: Path, name: str) -> None:
    body = "sandbox:\n  provider_id: sbx-1\n  git_author:\n    name: " + json.dumps(name) + "\n"

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "git_author" in str(info.value)


@pytest.mark.parametrize("email", ["no-at-sign", "a b@c.d", "a@b@c"])
def test_git_author_email_must_be_simple_address(tmp_path: Path, email: str) -> None:
    body = "sandbox:\n  provider_id: sbx-1\n  git_author:\n    email: " + repr(email) + "\n"

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "git_author" in str(info.value)
