"""Сценарии platform-config 1 (секреты в YAML) и 2 (уникальность id workspace)."""

from pathlib import Path

import pytest
from harness_server.config import ConfigError, load_config

EXAMPLE_CONFIG = Path(__file__).resolve().parents[3] / "config" / "harness.example.yaml"

WORKSPACE_BLOCK = """\
  - id: {id}
    name: Проект {id}
    voice_aliases: ["{id}"]
    gitlab_project: group/{id}
"""

TAIL = """\
sandbox:
  provider_id: sbx-1
gitlab:
  base_url: https://gitlab.example.com
"""


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "harness.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_example_config_is_valid() -> None:
    config = load_config(EXAMPLE_CONFIG)

    assert [workspace.id for workspace in config.workspaces] == ["demo"]
    assert config.workspaces[0].default_branch == "main"
    assert config.workspaces[0].agent == "claude-code"


def test_secret_field_is_rejected_with_path(tmp_path: Path) -> None:
    body = (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    gitlab_project: group/demo\n"
        "    gitlab_token: glpat-leaked-value\n" + TAIL
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    message = str(info.value)
    assert "workspaces[0].gitlab_token" in message
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
    ],
)
def test_secret_like_keys_rejected_on_any_level(tmp_path: Path, key: str) -> None:
    body = (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    gitlab_project: group/demo\n"
        + TAIL
        + f"extra:\n  nested:\n    {key}: value-should-not-appear\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "value-should-not-appear" not in str(info.value)
    assert f"extra.nested.{key}" in str(info.value)


def test_duplicate_workspace_id_is_named(tmp_path: Path) -> None:
    body = (
        "workspaces:\n"
        + WORKSPACE_BLOCK.format(id="same")
        + WORKSPACE_BLOCK.format(id="same")
        + TAIL
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "same" in str(info.value)
    assert "повторяющийся" in str(info.value)


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    body = "workspaces:\n" + WORKSPACE_BLOCK.format(id="one") + "    unexpected_field: 1\n" + TAIL

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "workspaces[0].unexpected_field" in str(info.value)


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


def test_workspace_id_too_long_rejected(tmp_path: Path) -> None:
    long_id = "w" * 29
    body = "workspaces:\n" + WORKSPACE_BLOCK.format(id=long_id) + TAIL

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "workspaces[0].id" in str(info.value)


def test_workspace_id_with_colon_rejected(tmp_path: Path) -> None:
    body = "workspaces:\n" + WORKSPACE_BLOCK.format(id="a:b") + TAIL

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "workspaces[0].id" in str(info.value)


def test_workspace_id_28_chars_accepted(tmp_path: Path) -> None:
    # Максимум: префикс ws:<32 hex>: занимает 36 байт, на id остаётся 28 (D-28).
    config = load_config(
        _write(tmp_path, "workspaces:\n" + WORKSPACE_BLOCK.format(id="w" * 28) + TAIL)
    )

    assert config.workspaces[0].id == "w" * 28


def test_empty_document_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, ""))


def test_at_least_one_workspace_required(tmp_path: Path) -> None:
    body = "workspaces: []\n" + TAIL

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "workspaces" in str(info.value)


@pytest.mark.parametrize("key", ["tokens", "secrets", "passwd", "pwd", "credential", "credentials"])
def test_extended_secret_segments_rejected(tmp_path: Path, key: str) -> None:
    body = (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    gitlab_project: group/demo\n"
        + TAIL
        + f"extra:\n  gitlab_{key}: value-should-not-appear\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "value-should-not-appear" not in str(info.value)
    assert f"extra.gitlab_{key}" in str(info.value)


def test_gitlab_base_url_with_userinfo_rejected(tmp_path: Path) -> None:
    body = (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    gitlab_project: group/demo\n"
        "sandbox:\n"
        "  provider_id: sbx-1\n"
        "gitlab:\n"
        "  base_url: https://user:pass@gitlab.example.com\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    message = str(info.value)
    assert "gitlab.base_url" in message
    assert "pass" not in message


def test_gitlab_base_url_with_user_only_rejected(tmp_path: Path) -> None:
    body = (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    gitlab_project: group/demo\n"
        "sandbox:\n"
        "  provider_id: sbx-1\n"
        "gitlab:\n"
        "  base_url: https://user@gitlab.example.com\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "gitlab.base_url" in str(info.value)


_BASE_URL_TEMPLATE = (
    "workspaces:\n"
    "  - id: demo\n"
    "    name: Demo\n"
    "    voice_aliases: []\n"
    "    gitlab_project: group/demo\n"
    "sandbox:\n"
    "  provider_id: sbx-1\n"
    "gitlab:\n"
    '  base_url: "{url}"\n'
)


@pytest.mark.parametrize(
    "url",
    [
        "user:pass@gitlab.example.com",
        "https:/user:pw@gitlab.example.com",
        "//user:pw@gitlab.example.com",
        "ftp://gitlab.example.com",
        "gitlab.example.com",
        "https://user:pw@gitlab.example.com",
        "https://gitlab.example.com@evil.example.com",
    ],
)
def test_gitlab_url_forms_rejected(tmp_path: Path, url: str) -> None:
    # Строки без схемы http(s) и с userinfo без «//» раньше проходили проверку (security mvp-03).
    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, _BASE_URL_TEMPLATE.format(url=url)))

    message = str(info.value)
    assert "gitlab.base_url" in message
    assert "pass" not in message
    assert "pw" not in message
    assert "evil" not in message


def test_sandbox_versions_and_turn_limit_have_pinned_defaults(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, _workspace_body(agent_max_turns=None) + TAIL))

    assert config.sandbox.claude_code_version == "2.1.292"
    assert config.sandbox.openspec_version == "1.14.3"
    assert config.workspaces[0].agent_max_turns == 50


@pytest.mark.parametrize("value", [0, 501])
def test_agent_max_turns_out_of_range_rejected(tmp_path: Path, value: int) -> None:
    body = _workspace_body(agent_max_turns=value) + TAIL

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "workspaces[0].agent_max_turns" in str(info.value)


def test_sandbox_version_override_is_read(tmp_path: Path) -> None:
    body = (
        _workspace_body(agent_max_turns=None)
        + "sandbox:\n  provider_id: sbx-1\n  claude_code_version: 2.2.0\n"
        + "gitlab:\n  base_url: https://gitlab.example.com\n"
    )

    config = load_config(_write(tmp_path, body))

    assert config.sandbox.claude_code_version == "2.2.0"


def _workspace_body(agent_max_turns: int | None) -> str:
    body = (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    gitlab_project: group/demo\n"
    )
    if agent_max_turns is not None:
        body += f"    agent_max_turns: {agent_max_turns}\n"
    return body


@pytest.mark.parametrize(
    "version", ["latest", "2.1", "2.1.292-beta", "v2.1.292", "2.1.292; rm -rf /"]
)
def test_sandbox_version_must_be_semver(tmp_path: Path, version: str) -> None:
    body = (
        _workspace_body(agent_max_turns=None)
        + f"sandbox:\n  provider_id: sbx-1\n  claude_code_version: '{version}'\n"
        + "gitlab:\n  base_url: https://gitlab.example.com\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "sandbox.claude_code_version" in str(info.value)


WORKSPACE_ONLY = (
    "workspaces:\n"
    "  - id: demo\n"
    "    name: Demo\n"
    "    voice_aliases: []\n"
    "    gitlab_project: group/demo\n"
)


def test_gitlab_access_ref_accepts_vault_reference(tmp_path: Path) -> None:
    body = WORKSPACE_ONLY + TAIL + "  access_ref: vault:demo/gitlab/main\n"

    config = load_config(_write(tmp_path, body))

    assert config.gitlab.access_ref == "vault:demo/gitlab/main"


def test_gitlab_access_ref_must_be_vault_reference(tmp_path: Path) -> None:
    body = WORKSPACE_ONLY + TAIL + "  access_ref: glpat-plain\n"

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "access_ref" in str(info.value)
    assert "glpat-plain" not in str(info.value)


def test_memory_block_is_optional_and_parsed(tmp_path: Path) -> None:
    plain = load_config(_write(tmp_path, WORKSPACE_ONLY + TAIL))
    assert plain.sandbox.memory is None

    body = (
        WORKSPACE_ONLY
        + "sandbox:\n"
        + "  provider_id: sbx-1\n"
        + "  memory:\n"
        + "    version: 1.2.3\n"
        + "    embedding_ref: vault:demo/polza/embeddings\n"
        + "gitlab:\n"
        + "  base_url: https://gitlab.example.com\n"
    )
    config = load_config(_write(tmp_path, body))

    assert config.sandbox.memory is not None
    assert config.sandbox.memory.version == "1.2.3"
    assert config.sandbox.memory.embedding_ref == "vault:demo/polza/embeddings"


def test_memory_version_must_be_semver(tmp_path: Path) -> None:
    body = (
        WORKSPACE_ONLY
        + "sandbox:\n"
        + "  provider_id: sbx-1\n"
        + "  memory:\n"
        + "    version: latest\n"
        + "gitlab:\n"
        + "  base_url: https://gitlab.example.com\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "memory.version" in str(info.value)


def test_memory_embedding_ref_must_be_vault_reference(tmp_path: Path) -> None:
    body = (
        WORKSPACE_ONLY
        + "sandbox:\n"
        + "  provider_id: sbx-1\n"
        + "  memory:\n"
        + "    version: 1.2.3\n"
        + "    embedding_ref: sk-plain-key-value\n"
        + "gitlab:\n"
        + "  base_url: https://gitlab.example.com\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "sk-plain-key-value" not in str(info.value)
