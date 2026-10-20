"""Загрузка и проверка config/harness.yaml: несекретные настройки workspace (в том числе
репозиторий), sandbox.

Секреты в YAML запрещены: ключи с сегментами token/tokens/key/password/passwd/pwd/secret/secrets/
apikey/credential/credentials отклоняются до валидации Pydantic (D-20, D-26). Ошибки называют путь к
полю (workspaces[0].repo.token), но не значение.
"""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from harness_server.vault_ref import is_vault_ref


class ConfigError(Exception):
    """Ошибка harness.yaml. Сообщение содержит путь к полю, но не значения."""


_SECRET_SEGMENTS = frozenset(
    {
        "token",
        "tokens",
        "key",
        "password",
        "passwd",
        "pwd",
        "secret",
        "secrets",
        "apikey",
        "credential",
        "credentials",
    }
)
_SEGMENT_SPLIT = re.compile(r"[_-]")
# Граница camelCase: accessToken → access_Token, чтобы сегмент token не терялся внутри слова.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# Версия пакета в bootstrap подставляется в команду npm: принимаем только X.Y.Z (D-38).
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
# memory-agent ставится по полному sha: теги и ветки изменяемы, короткий sha неоднозначен (D-51).
_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
# Сегмент начинается и заканчивается буквой или цифрой: ./. и ../.. не проходят (L1).
_GITHUB_REPO_SEGMENT = r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?"
_GITHUB_REPO_PATTERN = rf"^{_GITHUB_REPO_SEGMENT}/{_GITHUB_REPO_SEGMENT}$"
# GitLab допускает подгруппы: group/subgroup/name, минимум два сегмента (D-60).
_GITLAB_PROJECT_PATTERN = rf"^{_GITHUB_REPO_SEGMENT}(/{_GITHUB_REPO_SEGMENT})+$"
# Автор коммитов: без управляющих символов (в том числе перевода строки); адрес без @ и пробелов.
_GIT_NAME_PATTERN = r"^[^\x00-\x1f\x7f]+$"
_GIT_EMAIL_PATTERN = r"^[^@\s\x00-\x1f\x7f]+@[^@\s\x00-\x1f\x7f]+$"

# Провайдер git-хостинга репозитория workspace (D-60); GitHub Enterprise пока не поддержан.
GitProviderName = Literal["github", "gitlab"]
GITHUB_BASE_URL: Final = "https://github.com"
DEFAULT_REPO_BASE_URLS: Final[Mapping[str, str]] = {
    "github": GITHUB_BASE_URL,
    "gitlab": "https://gitlab.com",
}
# Метка хоста и сегмент пути base_url начинаются и заканчиваются буквой или цифрой: «.», «..»,
# «-host» и «a..b» не проходят (D-62, F3).
_HOST_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
_URL_PATH_SEGMENT = r"[A-Za-z0-9]([A-Za-z0-9._~-]*[A-Za-z0-9])?"
# Только https: заголовок с ключом не уходит открытым текстом (D-60). Без query, fragment, пробелов.
_REPO_BASE_URL_PATTERN = (
    rf"^https://{_HOST_LABEL}(\.{_HOST_LABEL})*(:[0-9]{{1,5}})?(/{_URL_PATH_SEGMENT})*/?$"
)


class RepoConfig(BaseModel):
    """Репозиторий workspace (D-60): провайдер, адрес, проект и ссылка vault на ключ записи.

    Адрес по умолчанию зависит от провайдера. Ключ не хранится здесь: access_ref — только ссылка
    vault (D-45), а без него задача не запускается, потому что все пайплайны пушат ветку.
    """

    model_config = ConfigDict(extra="forbid")

    provider: GitProviderName
    # Пустое значение заменяет валидатор по умолчанию провайдера (_default_base_url), см. ниже.
    base_url: str = ""
    project: str = Field(min_length=1, max_length=255)
    # Ключ записи из vault (D-45). Без него — только анонимный клон публичного репозитория.
    access_ref: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_base_url(cls, data: Any) -> Any:
        # Адрес по умолчанию подставляем до проверки поля, чтобы github без base_url не падал.
        if isinstance(data, dict) and data.get("base_url") is None:
            provider = data.get("provider")
            if isinstance(provider, str) and provider in DEFAULT_REPO_BASE_URLS:
                return {**data, "base_url": DEFAULT_REPO_BASE_URLS[provider]}
        return data

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        # Текст ошибки не содержит значения: pydantic выводит его без input (см. _format_errors).
        if "@" in value:
            raise ValueError(
                "адрес не должен содержать учётные данные перед символом @; "
                "ключ задаётся ссылкой repo.access_ref"
            )
        if re.fullmatch(_REPO_BASE_URL_PATTERN, value) is None:
            raise ValueError(
                "адрес репозитория — https://хост[:порт][/путь] без учётных данных, query, fragment"
            )
        return value.rstrip("/")

    @field_validator("access_ref")
    @classmethod
    def _check_access_ref(cls, value: str | None) -> str | None:
        return _check_vault_ref(value, "access_ref")

    @model_validator(mode="after")
    def _check_provider_rules(self) -> Self:
        if self.project.lower().endswith(".git"):
            raise ValueError("project указывается без .git")
        if self.provider == "github":
            if self.base_url != GITHUB_BASE_URL:
                raise ValueError(
                    "GitHub Enterprise пока не поддерживается: для github base_url — https://github.com"
                )
            if re.fullmatch(_GITHUB_REPO_PATTERN, self.project) is None:
                raise ValueError("project для github — owner/name")
        elif re.fullmatch(_GITLAB_PROJECT_PATTERN, self.project) is None:
            raise ValueError("project для gitlab — group[/subgroup]/name")
        return self


class WorkspaceConfig(BaseModel):
    """Проект, с которым работает харнесс: репозиторий GitHub или GitLab и команда тестов."""

    model_config = ConfigDict(extra="forbid")

    # id входит в callback_data `ws:<task hex>:<id>` ≤ 64 байт (D-28): до 28 символов, без «:».
    id: str = Field(min_length=1, max_length=28, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1)
    voice_aliases: list[str]
    repo: RepoConfig
    default_branch: str = "main"
    test_command: str | None = None
    agent: str = "claude-code"
    # Лимит ходов агента на задачу (D-38): ограничивает расход подписки и зацикливание.
    agent_max_turns: int = Field(default=50, ge=1, le=500)

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_fields(cls, data: Any) -> Any:
        # Чистый разрыв (D-60): старое поле не переводится молча, иначе ключ одного хоста уйдёт на
        # другой.
        if isinstance(data, dict) and "gitlab_project" in data:
            raise ValueError(
                "gitlab_project удалён (D-60): задайте repo: provider, project, access_ref"
            )
        return data


class SandboxMemoryConfig(BaseModel):
    """Память проекта в песочнице (memory-agent, D-47). Нет блока — память выключена."""

    model_config = ConfigDict(extra="forbid")

    # GitHub-репозиторий memory-agent (D-51).
    repo: str = Field(default="w1do/memory-agent", pattern=_GITHUB_REPO_PATTERN)
    # Полный sha коммита memory-agent, тег и ветка не принимаются (D-51). Обязателен.
    ref: str = Field(pattern=_GIT_SHA_PATTERN)
    # Ключ embeddings — только ссылка vault:…; без неё поиск лексический.
    embedding_ref: str | None = None

    @field_validator("embedding_ref")
    @classmethod
    def _check_embedding_ref(cls, value: str | None) -> str | None:
        return _check_vault_ref(value, "embedding_ref")


class GitAuthorConfig(BaseModel):
    """Автор коммитов агента в песочнице: git config --global при bootstrap (найдено live 5.7)."""

    model_config = ConfigDict(extra="forbid")

    # Без управляющих символов и перевода строки: значение идёт в git config и команду bootstrap.
    name: str = Field(
        default="agents-flow", min_length=1, max_length=100, pattern=_GIT_NAME_PATTERN
    )
    email: str = Field(
        default="agents-flow@noreply.local", max_length=254, pattern=_GIT_EMAIL_PATTERN
    )

    @field_validator("name")
    @classmethod
    def _check_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("не должен быть пустым или из пробелов")
        return value


class SandboxConfig(BaseModel):
    """Песочница. В MVP — одна, созданная вручную; id выдаёт провайдер."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1)
    # Версии ставятся в песочницу bootstrap-скриптом и закреплены здесь, а не «latest» (D-38).
    claude_code_version: str = Field(default="2.1.292", pattern=_SEMVER_PATTERN)
    openspec_version: str = Field(default="1.14.3", pattern=_SEMVER_PATTERN)
    memory: SandboxMemoryConfig | None = None
    git_author: GitAuthorConfig = Field(default_factory=GitAuthorConfig)


class HarnessConfig(BaseModel):
    """Корень harness.yaml."""

    model_config = ConfigDict(extra="forbid")

    workspaces: list[WorkspaceConfig] = Field(min_length=1)
    sandbox: SandboxConfig

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_gitlab_section(cls, data: Any) -> Any:
        # Секция gitlab удалена (D-60); без подсказки extra=forbid дал бы безликое «не разрешено».
        if isinstance(data, dict) and "gitlab" in data:
            raise ValueError(
                "секция gitlab удалена (D-60): адрес, проект и ключ задаются в workspaces[].repo"
            )
        return data

    @model_validator(mode="after")
    def _check_unique_workspace_ids(self) -> Self:
        seen: set[str] = set()
        for workspace in self.workspaces:
            if workspace.id in seen:
                raise ValueError(f"повторяющийся workspace id: {workspace.id}")
            seen.add(workspace.id)
        return self


def _check_vault_ref(value: str | None, field: str) -> str | None:
    """Поле с секретом допускает только ссылку vault:<project>/<service>/<name>.

    Значение секрета в YAML запрещено (D-20): ошибка называет поле, но не текст значения.
    """
    if value is not None and not is_vault_ref(value):
        raise ValueError(f"{field}: ожидается ссылка vault:<project>/<service>/<name>")
    return value


def load_config(path: Path) -> HarnessConfig:
    """Читает и валидирует файл конфигурации. Бросает ConfigError при любой проблеме."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"файл конфигурации не найден: {path}") from None
    except UnicodeDecodeError:
        # Бинарный или не-UTF-8 файл: исключение содержит фрагмент содержимого, поэтому не выводим.
        raise ConfigError(f"{path}: файл не является текстом в UTF-8") from None
    except OSError as exc:
        raise ConfigError(f"не удалось прочитать {path}: {exc.strerror}") from None

    try:
        raw = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError, ValueError):
        # Текст исключения PyYAML показывает фрагмент файла, поэтому его не выводим.
        raise ConfigError(f"{path}: некорректный YAML") from None
    if not isinstance(raw, dict) or not raw:
        raise ConfigError(f"{path}: ожидается непустой YAML-объект")

    try:
        _reject_secret_fields(raw)
    except RecursionError:
        raise ConfigError(f"{path}: слишком глубокая вложенность") from None
    try:
        return HarnessConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {_format_errors(exc)}") from None


def _key_segments(key: str) -> list[str]:
    """Сегменты имени поля: разделители _ и -, а также границы camelCase, в нижнем регистре."""
    return _SEGMENT_SPLIT.split(_CAMEL_BOUNDARY.sub("_", key).lower())


def _reject_secret_fields(node: Any, path: str = "") -> None:
    """Рекурсивно отклоняет ключи, похожие на секрет. Проверка до Pydantic, на любом уровне."""
    if isinstance(node, dict):
        for key, value in node.items():
            key_path = f"{path}.{key}" if path else str(key)
            if _SECRET_SEGMENTS.intersection(_key_segments(str(key))):
                raise ConfigError(
                    f"{key_path}: поле похоже на секрет; секреты задаются в ENV, "
                    "а не в harness.yaml"
                )
            _reject_secret_fields(value, key_path)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _reject_secret_fields(item, f"{path}[{index}]")


def _format_errors(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors(include_url=False, include_input=False, include_context=False):
        location = _format_location(err["loc"])
        parts.append(f"{location}: {err['msg']}" if location else str(err["msg"]))
    return "; ".join(parts)


def _format_location(loc: tuple[int | str, ...]) -> str:
    result = ""
    for part in loc:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result = f"{result}.{part}" if result else part
    return result
