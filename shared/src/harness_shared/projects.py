"""Проект (workspace): контракт между сервером, консолью, ботом и машиной агента (project-catalog).

Здесь единственное описание полей проекта. Сервер проверяет вход этими моделями до записи в БД, а
машина агента проверяет ответ `GET /api/projects/{id}/settings` перед записью локального конфига.
Ключ репозитория сюда не попадает: только ссылка vault в `access_ref` (D-45).
"""

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness_shared.vault_ref import is_vault_ref

# id входит в callback_data кнопки `ws:<task hex>:<id>` ≤ 64 байт (D-28): не длиннее 28 символов.
PROJECT_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9-]{0,27}$"
MAX_AGENT_TURNS: Final = 500

# Провайдер git-хостинга репозитория проекта (D-60); GitHub Enterprise пока не поддержан.
GitProviderName = Literal["github", "gitlab"]
GITHUB_BASE_URL: Final = "https://github.com"
GITLAB_BASE_URL: Final = "https://gitlab.com"
DEFAULT_REPO_BASE_URLS: Final[dict[str, str]] = {
    "github": GITHUB_BASE_URL,
    "gitlab": GITLAB_BASE_URL,
}
_GITHUB_REPO_SEGMENT = r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?"
_GITHUB_REPO_PATTERN = rf"^{_GITHUB_REPO_SEGMENT}/{_GITHUB_REPO_SEGMENT}$"
# GitLab допускает подгруппы: group/subgroup/name, минимум два сегмента (D-60).
_GITLAB_PROJECT_PATTERN = rf"^{_GITHUB_REPO_SEGMENT}(/{_GITHUB_REPO_SEGMENT})+$"
# Метка хоста и сегмент пути base_url начинаются и заканчиваются буквой или цифрой (D-62, F3).
_HOST_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
_URL_PATH_SEGMENT = r"[A-Za-z0-9]([A-Za-z0-9._~-]*[A-Za-z0-9])?"
# Только https: заголовок с ключом не уходит открытым текстом (D-60). Без query, fragment, пробелов.
_REPO_BASE_URL_PATTERN = (
    rf"^https://{_HOST_LABEL}(\.{_HOST_LABEL})*(:[0-9]{{1,5}})?(/{_URL_PATH_SEGMENT})*/?$"
)


class ProjectStatus(StrEnum):
    """Статус проекта: disabled не принимает новые задачи и не выдаётся машине агента (D-65)."""

    ACTIVE = "active"
    DISABLED = "disabled"


class ProjectRepo(BaseModel):
    """Репозиторий проекта (D-60): провайдер, адрес, проект и необязательная ссылка на ключ записи.

    Адрес по умолчанию зависит от провайдера. Ключ не хранится: access_ref — только ссылка vault.
    Без access_ref клон анонимный и подходит только для публичного репозитория.
    """

    model_config = ConfigDict(extra="forbid")

    provider: GitProviderName
    # Пустое значение заменяет адрес провайдера по умолчанию (_default_base_url).
    base_url: str = ""
    project: str = Field(min_length=1, max_length=255)
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
        # Текст ошибки не содержит значения: сервис выводит только имена полей.
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
        if value is not None and not is_vault_ref(value):
            raise ValueError("access_ref: ожидается ссылка vault:<project>/<service>/<name>")
        return value

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


def _check_voice_aliases(value: list[str]) -> list[str]:
    """Пустой алиас не может быть голосовой командой: отсекаем до записи."""
    if any(not alias.strip() for alias in value):
        raise ValueError("voice_aliases: пустой алиас")
    return value


class Workspace(BaseModel):
    """Проект, как его читают бот, worker и `agent init`: маршрутизация, задачи и конфиг агента.

    Один тип на весь сервер: сервис проектов отдаёт его всем потребителям (D-65).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=PROJECT_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    voice_aliases: list[str] = Field(default_factory=list, max_length=20)
    repo: ProjectRepo
    default_branch: str = Field(default="main", min_length=1, max_length=128)
    test_command: str | None = Field(default=None, max_length=2000)
    agent: str = Field(default="claude-code", min_length=1, max_length=32)
    # Лимит ходов агента на задачу (D-38): ограничивает расход подписки и зацикливание.
    agent_max_turns: int = Field(default=50, ge=1, le=MAX_AGENT_TURNS)

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_fields(cls, data: Any) -> Any:
        # Чистый разрыв (D-60): старое поле не переводится молча, иначе ключ уйдёт на другой хост.
        if isinstance(data, dict) and "gitlab_project" in data:
            raise ValueError(
                "gitlab_project удалён (D-60): задайте repo: provider, project, access_ref"
            )
        return data

    @field_validator("voice_aliases")
    @classmethod
    def _aliases_non_blank(cls, value: list[str]) -> list[str]:
        return _check_voice_aliases(value)


class ProjectInput(Workspace):
    """Поля, которые оператор задаёт при создании проекта. Лишние поля отклоняются."""


class ProjectUpdate(BaseModel):
    """Частичное изменение: передаются только изменяемые поля. id меняется только созданием.

    Блок repo передаётся целиком: без access_ref в нём ссылка на ключ снимается.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    voice_aliases: list[str] | None = Field(default=None, max_length=20)
    repo: ProjectRepo | None = None
    default_branch: str | None = Field(default=None, min_length=1, max_length=128)
    # Единственное необязательное поле: test_command можно сбросить в null.
    test_command: str | None = Field(default=None, max_length=2000)
    agent: str | None = Field(default=None, min_length=1, max_length=32)
    agent_max_turns: int | None = Field(default=None, ge=1, le=MAX_AGENT_TURNS)

    @field_validator("name", "voice_aliases", "repo", "default_branch", "agent", "agent_max_turns")
    @classmethod
    def _not_null(cls, value: object) -> object:
        """Обязательное поле нельзя сбросить в null: отсекаем до записи, а не на NOT NULL в базе."""
        if value is None:
            raise ValueError("null")
        return value

    @field_validator("voice_aliases")
    @classmethod
    def _aliases_non_blank(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _check_voice_aliases(value)


class ProjectRead(Workspace):
    """Проект, как его видит оператор: с присвоенным статусом и временем изменения."""

    status: ProjectStatus
    updated_at: datetime


class ProjectSettings(Workspace):
    """Настройки для локального конфига машины агента (`agent init`). Без значений ключей.

    Состав полей совпадает с Workspace: ключ виден машине агента только как ссылка access_ref.
    """
