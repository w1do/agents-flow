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
