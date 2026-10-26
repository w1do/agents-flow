"""Модель проекта (project-catalog, platform-config «Репозиторий workspace», D-60, D-65).

Проверки полей проекта и блока repo теперь живут в harness_shared.projects.Workspace: тот же тип
принимает API и консоль, поэтому сценарии валидации проверяются здесь напрямую, без YAML-конфига.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from harness_shared.projects import Workspace
from pydantic import ValidationError

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


def _write(tmp_path: Path, body: str) -> str:
    """Тело YAML-фрагмента: путь не нужен, проверка идёт по тексту."""
    del tmp_path
    return body


def _workspaces(body: str) -> list[Workspace]:
    """Проекты из блока `workspaces:` той же моделью, что принимает API; sandbox не читается."""
    raw = yaml.safe_load(body) or {}
    return [Workspace.model_validate(item) for item in raw.get("workspaces", [])]


def load_config(body: str) -> SimpleNamespace:
    """Совместимая обёртка: `.workspaces` — проверенные проекты; ошибки — ValidationError."""
    return SimpleNamespace(workspaces=_workspaces(body))


def _workspace_with_repo(repo_lines: str, tail: str = TAIL) -> str:
    """Конфиг с одним проектом; repo_lines — строки блока repo с отступом 6 (D-60)."""
    return (
        "workspaces:\n  - id: demo\n    name: Demo\n    voice_aliases: []\n    repo:\n"
        + repo_lines
        + tail
    )


def _text(exc: ValidationError) -> str:
    """Текст ошибок из полей и сообщений, без введённых значений (как в ответах API)."""
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False, include_context=False)
    )


def test_workspace_id_too_long_rejected(tmp_path: Path) -> None:
    long_id = "w" * 29
    body = "workspaces:\n" + WORKSPACE_BLOCK.format(id=long_id) + TAIL

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "id" in _text(info.value)


def test_workspace_id_with_colon_rejected(tmp_path: Path) -> None:
    body = "workspaces:\n" + WORKSPACE_BLOCK.format(id="a:b") + TAIL

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "id" in _text(info.value)


def test_workspace_id_28_chars_accepted(tmp_path: Path) -> None:
    # Максимум: префикс ws:<32 hex>: занимает 36 байт, на id остаётся 28 (D-28).
    config = load_config(
        _write(tmp_path, "workspaces:\n" + WORKSPACE_BLOCK.format(id="w" * 28) + TAIL)
    )

    assert config.workspaces[0].id == "w" * 28


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

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "repo.base_url" in _text(info.value)


def test_repo_base_url_with_userinfo_rejected(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: gitlab\n"
        "      base_url: https://user:pass@gitlab.example.com\n"
        "      project: group/demo\n"
    )

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    message = _text(info.value)
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

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    message = _text(info.value)
    assert "repo.base_url" in message
    assert "evil" not in message


def test_repo_github_enterprise_rejected(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: github\n"
        "      base_url: https://ghe.example.com\n"
        "      project: w1do/chistotyumen\n"
    )

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "GitHub Enterprise" in _text(info.value)


def test_repo_github_project_must_be_owner_name(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: github\n      project: group/sub/name\n")

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "owner/name" in _text(info.value)


def test_repo_gitlab_project_needs_group(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: gitlab\n      project: demo\n")

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "group" in _text(info.value)


def test_repo_project_with_dot_git_rejected(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: github\n      project: w1do/chistotyumen.git\n")

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert ".git" in _text(info.value)


def test_repo_unknown_provider_rejected(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: bitbucket\n      project: team/demo\n")

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "repo.provider" in _text(info.value)


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

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "access_ref" in _text(info.value)
    assert "github_pat_plain" not in _text(info.value)


def test_repo_access_ref_optional(tmp_path: Path) -> None:
    body = _workspace_with_repo("      provider: gitlab\n      project: group/demo\n")

    assert load_config(_write(tmp_path, body)).workspaces[0].repo.access_ref is None


def test_legacy_gitlab_project_rejected_with_hint(tmp_path: Path) -> None:
    body = (
        "workspaces:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        "    voice_aliases: []\n"
        "    gitlab_project: group/demo\n" + TAIL
    )

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "gitlab_project удалён" in _text(info.value)


def test_workspace_without_repo_rejected(tmp_path: Path) -> None:
    body = "workspaces:\n  - id: demo\n    name: Demo\n    voice_aliases: []\n" + TAIL

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "repo" in _text(info.value)


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


@pytest.mark.parametrize("turns", [0, 501])
def test_agent_max_turns_out_of_range_rejected(tmp_path: Path, turns: int) -> None:
    body = (
        "workspaces:\n  - id: demo\n    name: Demo\n    voice_aliases: []\n"
        "    repo:\n      provider: gitlab\n      project: group/demo\n"
        f"    agent_max_turns: {turns}\n"
        "sandbox:\n  provider_id: local\n"
    )
    with pytest.raises(ValidationError, match="agent_max_turns"):
        load_config(_write(tmp_path, body))


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

    with pytest.raises(ValidationError) as info:
        load_config(_write(tmp_path, body))

    assert "repo.base_url" in _text(info.value)


def test_repo_base_url_accepts_ip_port_and_path(tmp_path: Path) -> None:
    body = _workspace_with_repo(
        "      provider: gitlab\n"
        "      base_url: https://10.0.0.5:8443/git-lab\n"
        "      project: group/demo\n"
    )

    config = load_config(_write(tmp_path, body))

    repo = config.workspaces[0].repo
    assert repo.base_url == "https://10.0.0.5:8443/git-lab"
