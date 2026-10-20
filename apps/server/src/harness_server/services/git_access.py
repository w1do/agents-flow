"""Адрес и авторизация git для репозитория workspace (D-60, D-62; уточняет D-52).

Ключ уходит git только заголовком Authorization в env одной git-команды, на префикс адреса этого
репозитория. Команда с ключом перекрывает настройки из .git/config клона, ~/.gitconfig и
/etc/gitconfig, которые агент может править (D-62). Значения ключей и заголовков в логи и
исключения не попадают.
"""

import base64
import shlex
from collections.abc import Mapping
from typing import Final
from urllib.parse import quote

from harness_server.config import GitProviderName, RepoConfig

# Пользователь Basic по провайдеру: GitLab принимает oauth2 (D-52, live 6c), GitHub — x-access-token
# (тот же способ, что у actions/checkout; имя пользователя для PAT не используется, токен — пароль).
GIT_BASIC_USERS: Final[Mapping[GitProviderName, str]] = {
    "gitlab": "oauth2",
    "github": "x-access-token",
}
# Слово для владельца: у GitLab merge request, у GitHub pull request; внутри харнесса — «MR» (D-56).
CHANGE_REQUEST_LABELS: Final[Mapping[GitProviderName, str]] = {"gitlab": "MR", "github": "PR"}

# fetch идёт по адресу из конфига, а не по имени origin: remote.origin.* клона в команде не
# участвуют, а ветки попадают в refs/remotes/origin/* явной refspec (D-62).
FETCH_REFSPEC: Final = "+refs/heads/*:refs/remotes/origin/*"
# Хранилище CA Ubuntu в шаблоне песочницы: явный путь перекрывает sslCAInfo/sslCAPath клона (D-62).
SYSTEM_CA_BUNDLE: Final = "/etc/ssl/certs/ca-certificates.crt"
SYSTEM_CA_DIR: Final = "/etc/ssl/certs"
# http.<префикс>.* на том же префиксе, что и заголовок. git берёт самый точный URL, при равной
# точности — последнее значение, а scope command читается последним, поэтому http.<url>.* из
# .git/config клона эти значения не перекрывают (D-62). Пустой proxy выключает и прокси из env.
SCOPED_HTTP_OVERRIDES: Final[tuple[tuple[str, str], ...]] = (
    ("followRedirects", "false"),
    ("proxy", ""),
    ("sslVerify", "true"),
    ("sslCAInfo", SYSTEM_CA_BUNDLE),
    ("sslCAPath", SYSTEM_CA_DIR),
)
# Параметры без URL: хуки, помощники учётных данных и дочерние процессы git получили бы env с
# заголовком (D-62). Пустой credential.helper сбрасывает список помощников из всех файлов.
COMMAND_OVERRIDES: Final[tuple[tuple[str, str], ...]] = (
    ("credential.helper", ""),
    ("core.hooksPath", "/dev/null"),
    ("core.fsmonitor", "false"),
    ("core.alternateRefsCommand", "true"),
    ("gc.auto", "0"),
    ("maintenance.auto", "false"),
    ("fetch.recurseSubmodules", "false"),
    ("submodule.recurse", "false"),
)
# env любой git-команды харнесса: без ~/.gitconfig и /etc/gitconfig, только https (insteadOf на
# ext:: или file:// не сработает), askpass не запускает чужую программу (D-62).
HARDENED_GIT_ENV: Final[Mapping[str, str]] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/bin/false",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_ALLOW_PROTOCOL": "https",
}


def clone_url(repo: RepoConfig) -> str:
    """Адрес клона: base_url + проект + .git. Учётных данных в адресе нет."""
    return f"{repo.base_url}/{repo.project}.git"


def auth_url_prefix(repo: RepoConfig) -> str:
    """Префикс http.<url>.* для заголовка: только этот репозиторий (граница «/»).

    git сопоставляет http.<url>.* по префиксу на границе «/», поэтому с завершающим «/» заголовок
    не получает соседний репозиторий того же хоста (D-60).
    """
    return f"{clone_url(repo)}/"


def git_auth_header(provider: GitProviderName, token: str) -> str:
    """Authorization: Basic base64("<user>:<token>"), user по провайдеру. Значение — секрет."""
    basic = base64.b64encode(f"{GIT_BASIC_USERS[provider]}:{token}".encode()).decode("ascii")
    return f"Authorization: Basic {basic}"


def git_auth_env(repo: RepoConfig, token: str) -> dict[str, str]:
    """env git-команды с ключом: заголовок на префикс репозитория и перекрытия конфига (D-62).

    GIT_CONFIG_* передаются через env одной команды, а не argv и не файлы (D-52); git >= 2.32.
    Заголовок — всегда пара с номером 0.
    """
    prefix = auth_url_prefix(repo)
    pairs: list[tuple[str, str]] = [
        (f"http.{prefix}.extraHeader", git_auth_header(repo.provider, token)),
        *((f"http.{prefix}.{name}", value) for name, value in SCOPED_HTTP_OVERRIDES),
        *COMMAND_OVERRIDES,
    ]
    env = dict(HARDENED_GIT_ENV)
    env["GIT_CONFIG_COUNT"] = str(len(pairs))
    for index, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def anonymous_git_env() -> dict[str, str]:
    """env git-команды без ключа: без запроса пароля и без ~/.gitconfig и /etc/gitconfig."""
    return dict(HARDENED_GIT_ENV)


def clone_command(repo: RepoConfig, repo_dir: str) -> str:
    """Клон по адресу из конфига без подмодулей: подмодуль запустил бы git с чужим конфигом."""
    return shlex.join(
        ["git", "clone", "--quiet", "--no-recurse-submodules", "--", clone_url(repo), repo_dir]
    )


def set_origin_command(repo: RepoConfig, repo_dir: str) -> str:
    """Возвращает origin клона на адрес из конфига: агент мог его поменять.

    Выполняется без ключа.
    """
    return shlex.join(["git", "-C", repo_dir, "remote", "set-url", "origin", clone_url(repo)])


def fetch_command(repo: RepoConfig, repo_dir: str) -> str:
    """fetch по адресу из конфига с явной refspec и без подмодулей (D-62)."""
    return shlex.join(
        [
            "git",
            "-C",
            repo_dir,
            "fetch",
            "--quiet",
            "--prune",
            "--no-recurse-submodules",
            clone_url(repo),
            FETCH_REFSPEC,
        ]
    )


def git_auth_secret_values(provider: GitProviderName, token: str) -> tuple[str, str, str]:
    """Секреты заголовка для redaction: строка заголовка, её base64 и base64 в URL-кодировке."""
    header = git_auth_header(provider, token)
    bare = header.removeprefix("Authorization: Basic ")
    return header, bare, quote(bare, safe="")


def change_request_label(provider: GitProviderName) -> str:
    """«MR» или «PR» для текстов владельцу (mvp-09)."""
    return CHANGE_REQUEST_LABELS[provider]
