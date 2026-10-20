"""Адрес и авторизация git для репозитория workspace (D-60, D-52, D-62).

Заголовок привязан к префиксу репозитория, команда с ключом перекрывает настройки конфига,
которые агент мог записать в клон.
"""

import base64
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
from harness_server.config import RepoConfig
from harness_server.security.redaction import redact
from harness_server.services import git_access

TOKEN = "glpat-ABCDEFGHIJKLMNOPQR"


def _github() -> RepoConfig:
    return RepoConfig(provider="github", base_url="https://github.com", project="w1do/chistotyumen")


def _gitlab_subgroup() -> RepoConfig:
    return RepoConfig(provider="gitlab", base_url="https://gitlab.com", project="group/sub/demo")


def _gitlab_demo() -> RepoConfig:
    return RepoConfig(provider="gitlab", base_url="https://gitlab.com", project="group/demo")


def _git_supports_config_env() -> bool:
    # GIT_CONFIG_COUNT / GIT_CONFIG_KEY_<i> появились в git 2.31 (D-52); проверка с запасом до 2.32.
    if shutil.which("git") is None:
        return False
    out = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"(\d+)\.(\d+)", out)
    if match is None:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (2, 32)


requires_git_config_env = pytest.mark.skipif(
    not _git_supports_config_env(), reason="нужен git >= 2.32 (GIT_CONFIG_COUNT в env)"
)


def test_clone_url_github() -> None:
    assert git_access.clone_url(_github()) == "https://github.com/w1do/chistotyumen.git"


def test_clone_url_gitlab_subgroup() -> None:
    assert git_access.clone_url(_gitlab_subgroup()) == "https://gitlab.com/group/sub/demo.git"


def test_git_auth_header_uses_oauth2_for_gitlab() -> None:
    header = git_access.git_auth_header("gitlab", "tok")

    assert header == "Authorization: Basic " + base64.b64encode(b"oauth2:tok").decode("ascii")


def test_git_auth_header_uses_x_access_token_for_github() -> None:
    header = git_access.git_auth_header("github", "tok")

    assert header == "Authorization: Basic " + base64.b64encode(b"x-access-token:tok").decode(
        "ascii"
    )


def test_git_auth_env_overrides_clone_config() -> None:
    env = git_access.git_auth_env(_github(), "tok")
    prefix = "https://github.com/w1do/chistotyumen.git/"

    # Заголовок привязан к адресу репозитория с завершающим «/», а не ко всему хосту (D-60).
    assert env["GIT_CONFIG_COUNT"] == "14"
    assert env["GIT_CONFIG_KEY_0"] == f"http.{prefix}.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"] == git_access.git_auth_header("github", "tok")
    pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(14)}
    for name, value in git_access.SCOPED_HTTP_OVERRIDES:
        assert pairs[f"http.{prefix}.{name}"] == value
    for name, value in git_access.COMMAND_OVERRIDES:
        assert pairs[name] == value
    for name, value in git_access.HARDENED_GIT_ENV.items():
        assert env[name] == value


def test_anonymous_git_env_is_hardened_without_header() -> None:
    env = git_access.anonymous_git_env()

    assert env == dict(git_access.HARDENED_GIT_ENV)
    assert "GIT_CONFIG_COUNT" not in env
    assert all("Authorization" not in value for value in env.values())


def test_clone_command_disables_submodules() -> None:
    command = git_access.clone_command(_gitlab_demo(), "/home/user/work/demo")

    assert command == (
        "git clone --quiet --no-recurse-submodules -- https://gitlab.com/group/demo.git "
        "/home/user/work/demo"
    )


def test_set_origin_command_uses_config_url() -> None:
    command = git_access.set_origin_command(_gitlab_demo(), "/home/user/work/demo")

    assert command == (
        "git -C /home/user/work/demo remote set-url origin https://gitlab.com/group/demo.git"
    )


def test_fetch_command_uses_config_url_and_refspec() -> None:
    command = git_access.fetch_command(_gitlab_demo(), "/home/user/work/demo")

    assert command == (
        "git -C /home/user/work/demo fetch --quiet --prune --no-recurse-submodules "
        "https://gitlab.com/group/demo.git '+refs/heads/*:refs/remotes/origin/*'"
    )
    assert shlex.split(command)[-1] == "+refs/heads/*:refs/remotes/origin/*"


def test_git_auth_secret_values_include_urlencoded_base64() -> None:
    values = git_access.git_auth_secret_values("gitlab", TOKEN)
    header, bare, encoded = values

    assert header == git_access.git_auth_header("gitlab", TOKEN)
    assert bare == base64.b64encode(f"oauth2:{TOKEN}".encode()).decode("ascii")
    assert "=" in bare
    assert encoded == quote(bare, safe="")
    assert "%3D" in encoded
    # Все три формы секрета убираются из вывода, в котором они встречаются (D-62).
    output = redact("\n".join(values), extra_values=values)
    for secret in values:
        assert secret not in output


def test_change_request_label() -> None:
    assert git_access.change_request_label("gitlab") == "MR"
    assert git_access.change_request_label("github") == "PR"


def _git_env(tmp_path: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    # HOME во временном каталоге: ~/.gitconfig хозяина машины в тесте не участвует.
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    env.update(extra or {})
    return env


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _git_env(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], env=env, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        env=env,
        check=True,
    )
    return repo


def _git_config_file(repo: Path, key: str, value: str) -> None:
    subprocess.run(
        ["git", "config", "--file", str(repo / ".git" / "config"), key, value],
        env=_git_env(repo.parent),
        check=True,
    )


def _write_hook(path: Path, marker: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\n", encoding="utf-8")
    path.chmod(0o755)


@requires_git_config_env
def test_auth_env_disables_planted_hooks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    marker = tmp_path / "hook-ran"
    planted_dir = tmp_path / "planted-hooks"
    _write_hook(planted_dir / "reference-transaction", marker)
    _write_hook(repo / ".git" / "hooks" / "reference-transaction", marker)
    _git_config_file(repo, "core.hooksPath", str(planted_dir))

    env = git_access.git_auth_env(_gitlab_demo(), TOKEN)
    subprocess.run(
        ["git", "update-ref", "refs/heads/x", "HEAD"],
        cwd=repo,
        env=_git_env(tmp_path, env),
        check=True,
    )
    assert not marker.exists()

    # Контроль: без перекрытий подложенный хук выполняется.
    subprocess.run(["git", "update-ref", "refs/heads/y", "HEAD"], cwd=repo, env=_git_env(tmp_path))
    assert marker.exists()


@requires_git_config_env
def test_auth_env_overrides_planted_http_config(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    url = git_access.clone_url(_gitlab_demo())
    _git_config_file(repo, f"http.{url}.proxy", "http://evil.example.com:3128")
    _git_config_file(repo, f"http.{url}/.sslVerify", "false")
    _git_config_file(repo, "http.sslCAInfo", "/tmp/evil.pem")

    env = git_access.git_auth_env(_gitlab_demo(), TOKEN)
    with_env = _git_env(tmp_path, env)
    proxy = subprocess.run(
        ["git", "config", "--get-urlmatch", "http.proxy", url],
        cwd=repo,
        env=with_env,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    verify = subprocess.run(
        ["git", "config", "--get-urlmatch", "http.sslVerify", url],
        cwd=repo,
        env=with_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    ca_info = subprocess.run(
        ["git", "config", "--get-urlmatch", "http.sslCAInfo", url],
        cwd=repo,
        env=with_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert proxy == ""
    assert verify == "true"
    assert ca_info == git_access.SYSTEM_CA_BUNDLE

    # Контроль: без перекрытий в клоне действуют подложенные значения.
    control = subprocess.run(
        ["git", "config", "--get-urlmatch", "http.proxy", url],
        cwd=repo,
        env=_git_env(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert control == "http://evil.example.com:3128"


@requires_git_config_env
def test_auth_env_resets_planted_credential_helper(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    marker = tmp_path / "helper-ran"
    helper = f"!f() {{ touch {shlex.quote(str(marker))}; }}; f"
    _git_config_file(repo, "credential.helper", helper)
    _git_config_file(repo, "credential.https://gitlab.com.helper", helper)
    subprocess.run(
        ["git", "config", "--file", str(tmp_path / ".gitconfig"), "credential.helper", helper],
        env=_git_env(tmp_path),
        check=True,
    )
    request = "protocol=https\nhost=gitlab.com\npath=group/demo.git\n\n"

    env = git_access.git_auth_env(_gitlab_demo(), TOKEN)
    subprocess.run(
        ["git", "credential", "fill"],
        cwd=repo,
        env=_git_env(tmp_path, env),
        input=request,
        capture_output=True,
        text=True,
        check=False,
    )
    assert not marker.exists()

    # Контроль: без перекрытий помощник из клона запускается.
    subprocess.run(
        ["git", "credential", "fill"],
        cwd=repo,
        env=_git_env(tmp_path, {"GIT_TERMINAL_PROMPT": "0"}),
        input=request,
        capture_output=True,
        text=True,
        check=False,
    )
    assert marker.exists()
