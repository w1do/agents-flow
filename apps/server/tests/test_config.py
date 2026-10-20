"""Сценарии platform-config 1 (секреты в YAML) и 2 (уникальность id workspace)."""

import json
from pathlib import Path

import pytest
from harness_server.config import ConfigError, load_config

EXAMPLE_CONFIG = Path(__file__).resolve().parents[3] / "config" / "harness.example.yaml"
# Фиктивный sha для тестов (D-51): настоящий закреплённый коммит — только в harness.yaml и D-51.
MEMORY_REF = "0123456789abcdef0123456789abcdef01234567"

WORKSPACE_BLOCK = """\
  - id: {id}
    name: Проект {id}
    voice_aliases: ["{id}"]
    repo:
      provider: gitlab
      project: group/{id}
"""

TAIL = """\
sandbox:
  provider_id: sbx-1
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
        "    repo:\n      provider: gitlab\n      project: group/demo\n"
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
        "    repo:\n      provider: gitlab\n      project: group/demo\n"
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
        "    repo:\n      provider: gitlab\n      project: group/demo\n"
        + TAIL
        + f"extra:\n  gitlab_{key}: value-should-not-appear\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "value-should-not-appear" not in str(info.value)
    assert f"extra.gitlab_{key}" in str(info.value)


def _workspace_with_repo(repo_lines: str, tail: str = TAIL) -> str:
    """Конфиг с одним workspace; repo_lines — строки блока repo с отступом 6 (D-60)."""
    return (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    repo:\n" + repo_lines + tail
    )


def test_repo_github_defaults_base_url(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: github\n      project: w1do/chistotyumen\n")

    repo = load_config(_write(tmp_path, body)).workspaces[0].repo

    assert repo.provider == "github"
    assert repo.base_url == "https://github.com"
    assert repo.project == "w1do/chistotyumen"
    assert repo.access_ref is None


def test_repo_gitlab_defaults_base_url(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: gitlab\n      project: group/demo\n")

    repo = load_config(_write(tmp_path, body)).workspaces[0].repo

    assert repo.base_url == "https://gitlab.com"


def test_repo_gitlab_self_hosted_with_path(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: gitlab\n"
        "      base_url: https://host.example.com/gitlab\n"
        "      project: group/sub/demo\n"
    )

    repo = load_config(_write(tmp_path, body)).workspaces[0].repo

    assert repo.base_url == "https://host.example.com/gitlab"
    assert repo.project == "group/sub/demo"


def test_repo_base_url_trailing_slash_stripped(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: gitlab\n"
        '      base_url: "https://gitlab.example.com/"\n'
        "      project: group/demo\n"
    )

    repo = load_config(_write(tmp_path, body)).workspaces[0].repo

    assert repo.base_url == "https://gitlab.example.com"


def test_repo_base_url_http_rejected(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: gitlab\n"
        "      base_url: http://gitlab.example.com\n"
        "      project: group/demo\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "repo.base_url" in str(info.value)


def test_repo_base_url_with_userinfo_rejected(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: gitlab\n"
        "      base_url: https://user:pass@gitlab.example.com\n"
        "      project: group/demo\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    message = str(info.value)
    assert "repo.base_url" in message
    assert "pass" not in message


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.example.com?x=1",
        "https://gitlab.example.com#frag",
        "https://gitlab example.com",
        "gitlab.example.com",
        "ftp://gitlab.example.com",
    ],
)
def test_repo_base_url_forms_rejected(tmp_path: Path, url: str) -> None:
    body = _workspace_with_repo(
        f'      provider: gitlab\n      base_url: "{url}"\n      project: group/demo\n'
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    message = str(info.value)
    assert "repo.base_url" in message
    assert "evil" not in message


def test_repo_github_enterprise_rejected(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: github\n"
        "      base_url: https://ghe.example.com\n"
        "      project: w1do/chistotyumen\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "GitHub Enterprise" in str(info.value)


def test_repo_github_project_must_be_owner_name(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: github\n      project: group/sub/name\n")

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "owner/name" in str(info.value)


def test_repo_gitlab_project_needs_group(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: gitlab\n      project: demo\n")

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "group" in str(info.value)


def test_repo_project_with_dot_git_rejected(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: github\n      project: w1do/chistotyumen.git\n")

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert ".git" in str(info.value)


def test_repo_unknown_provider_rejected(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: bitbucket\n      project: team/demo\n")

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "repo.provider" in str(info.value)


def test_repo_access_ref_accepts_vault_reference(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: github\n      project: w1do/chistotyumen\n"
        "      access_ref: vault:demo/github/main\n"
    )

    repo = load_config(_write(tmp_path, body)).workspaces[0].repo

    assert repo.access_ref == "vault:demo/github/main"


def test_repo_access_ref_must_be_vault_reference(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: github\n"
        "      project: w1do/chistotyumen\n"
        "      access_ref: github_pat_plain\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "access_ref" in str(info.value)
    assert "github_pat_plain" not in str(info.value)


def test_repo_access_ref_optional(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: gitlab\n      project: group/demo\n")

    assert load_config(_write(tmp_path, body)).workspaces[0].repo.access_ref is None


def test_legacy_gitlab_section_rejected_with_hint(tmp_path: Path) -> None:
    body = (
        _workspace_with_repo("      provider: gitlab\n      project: group/demo\n")
        + "sandbox:\n  provider_id: sbx-1\n"
        + "gitlab:\n  base_url: https://gitlab.example.com\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "секция gitlab удалена" in str(info.value)


def test_legacy_gitlab_project_rejected_with_hint(tmp_path: Path) -> None:
    body = (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    gitlab_project: group/demo\n" + TAIL
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "gitlab_project удалён" in str(info.value)


def test_workspace_without_repo_rejected(tmp_path: Path) -> None:
    body = "workspaces:\n  - id: demo\n    name: Demo\n    voice_aliases: []\n" + TAIL

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "workspaces[0].repo" in str(info.value)


def test_workspaces_with_different_providers_accepted(tmp_path: Path) -> None:
    body = (
        "workspaces:\n"
        "  - id: site\n"
        "    name: Site\n"
        "    voice_aliases: []\n"
        "    repo:\n"
        "      provider: github\n"
        "      project: w1do/chistotyumen\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    repo:\n"
        "      provider: gitlab\n"
        "      project: group/demo\n" + TAIL
    )

    config = load_config(_write(tmp_path, body))

    assert [ws.repo.provider for ws in config.workspaces] == ["github", "gitlab"]


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
    )

    config = load_config(_write(tmp_path, body))

    assert config.sandbox.claude_code_version == "2.2.0"


def _workspace_body(agent_max_turns: int | None) -> str:
    body = (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    repo:\n      provider: gitlab\n      project: group/demo\n"
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
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "sandbox.claude_code_version" in str(info.value)


WORKSPACE_ONLY = (
    "workspaces:\n"
    "  - id: demo\n"
    "    name: Demo\n"
    "    voice_aliases: []\n"
    "    repo:\n      provider: gitlab\n      project: group/demo\n"
)


def _memory_body(memory_lines: str) -> str:
    """Конфиг с блоком sandbox.memory; memory_lines — строки под memory (с отступом 4)."""
    return WORKSPACE_ONLY + "sandbox:\n" + "  provider_id: sbx-1\n" + "  memory:\n" + memory_lines


def test_memory_block_is_optional_and_parsed(tmp_path: Path) -> None:
    plain = load_config(_write(tmp_path, WORKSPACE_ONLY + TAIL))
    assert plain.sandbox.memory is None

    body = _memory_body(f"    ref: {MEMORY_REF}\n    embedding_ref: vault:demo/polza/embeddings\n")
    config = load_config(_write(tmp_path, body))

    assert config.sandbox.memory is not None
    assert config.sandbox.memory.ref == MEMORY_REF
    assert config.sandbox.memory.repo == "w1do/memory-agent"
    assert config.sandbox.memory.embedding_ref == "vault:demo/polza/embeddings"


@pytest.mark.parametrize(
    "ref",
    [
        "v1.0.0",  # тег изменяем
        "main",  # ветка изменяема
        "09e5e63",  # короткий sha неоднозначен
        MEMORY_REF.upper(),  # sha в верхнем регистре
        MEMORY_REF + "0",  # 41 символ
    ],
)
def test_memory_ref_must_be_full_commit_sha(tmp_path: Path, ref: str) -> None:
    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, _memory_body(f"    ref: {ref}\n")))

    assert "memory.ref" in str(info.value)
    assert ref not in str(info.value)


def test_memory_ref_is_required(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_config(
            _write(tmp_path, _memory_body("    embedding_ref: vault:demo/polza/embeddings\n"))
        )

    assert "memory.ref" in str(info.value)


@pytest.mark.parametrize("repo", ["a/b/c", "w1do", "w1do/memory agent"])
def test_memory_repo_must_be_owner_slash_name(tmp_path: Path, repo: str) -> None:
    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, _memory_body(f"    repo: {repo}\n    ref: {MEMORY_REF}\n")))

    assert "memory.repo" in str(info.value)


@pytest.mark.parametrize("repo", ["../..", "./.", "-x/y", "x./y", "w1do/-agent", "w1do/agent."])
def test_memory_repo_segments_must_start_and_end_with_alnum(tmp_path: Path, repo: str) -> None:
    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, _memory_body(f"    repo: {repo}\n    ref: {MEMORY_REF}\n")))

    assert "memory.repo" in str(info.value)


def test_memory_repo_accepts_fork_name(tmp_path: Path) -> None:
    body = _memory_body(f"    repo: other-org/memory-agent.fork\n    ref: {MEMORY_REF}\n")

    config = load_config(_write(tmp_path, body))

    assert config.sandbox.memory is not None
    assert config.sandbox.memory.repo == "other-org/memory-agent.fork"


def test_memory_version_field_is_rejected(tmp_path: Path) -> None:
    body = _memory_body(f"    version: 1.2.3\n    ref: {MEMORY_REF}\n")

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "version" in str(info.value)


def test_memory_embedding_ref_must_be_vault_reference(tmp_path: Path) -> None:
    body = (
        WORKSPACE_ONLY
        + "sandbox:\n"
        + "  provider_id: sbx-1\n"
        + "  memory:\n"
        + f"    ref: {MEMORY_REF}\n"
        + "    embedding_ref: sk-plain-key-value\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "sk-plain-key-value" not in str(info.value)


def test_git_author_defaults_when_block_absent(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, WORKSPACE_ONLY + TAIL))

    assert config.sandbox.git_author.name == "agents-flow"
    assert config.sandbox.git_author.email == "agents-flow@noreply.local"


def test_git_author_custom_values_accepted(tmp_path: Path) -> None:
    body = (
        WORKSPACE_ONLY
        + "sandbox:\n  provider_id: sbx-1\n  git_author:\n    name: Agent Bot\n"
        + "    email: bot@example.com\n"
    )

    config = load_config(_write(tmp_path, body))

    assert config.sandbox.git_author.name == "Agent Bot"
    assert config.sandbox.git_author.email == "bot@example.com"


@pytest.mark.parametrize("name", ["   ", "a\nb", "x" * 101])
def test_git_author_name_rejected_when_blank_control_or_long(tmp_path: Path, name: str) -> None:
    body = (
        WORKSPACE_ONLY
        + "sandbox:\n  provider_id: sbx-1\n  git_author:\n    name: "
        + json.dumps(name)
        + "\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "git_author" in str(info.value)


@pytest.mark.parametrize("email", ["no-at-sign", "a b@c.d", "a@b@c"])
def test_git_author_email_must_be_simple_address(tmp_path: Path, email: str) -> None:
    body = (
        WORKSPACE_ONLY
        + "sandbox:\n  provider_id: sbx-1\n  git_author:\n    email: "
        + repr(email)
        + "\n"
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "git_author" in str(info.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.example.com/..",
        "https://gitlab.example.com/.",
        "https://gitlab.example.com/a/../b",
        "https://-gitlab.example.com",
        "https://gitlab..example.com",
        "https://gitlab.example.com/-x",
    ],
)
def test_repo_base_url_rejects_dot_and_dash_segments(tmp_path: Path, url: str) -> None:
    body = _workspace_with_repo(
        f'      provider: gitlab\n      base_url: "{url}"\n      project: group/demo\n'
    )

    with pytest.raises(ConfigError) as info:
        load_config(_write(tmp_path, body))

    assert "repo.base_url" in str(info.value)


def test_repo_base_url_accepts_ip_port_and_path(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: gitlab\n"
        "      base_url: https://10.0.0.5:8443/git-lab\n"
        "      project: group/demo\n"
    )

    config = load_config(_write(tmp_path, body))

    repo = config.workspaces[0].repo
    assert repo.base_url == "https://10.0.0.5:8443/git-lab"
