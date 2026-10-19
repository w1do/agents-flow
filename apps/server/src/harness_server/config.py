"""Загрузка и проверка config/harness.yaml: несекретные настройки workspace, sandbox, gitlab.

Секреты в YAML запрещены: ключи с сегментами token/tokens/key/password/passwd/pwd/secret/secrets/
apikey/credential/credentials отклоняются до валидации Pydantic (D-20, D-26). Ошибки называют путь к
полю (workspaces[0].gitlab_token), но не значение.
"""

import re
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


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


class WorkspaceConfig(BaseModel):
    """Проект, с которым работает харнесс: GitLab-репозиторий и команда тестов."""

    model_config = ConfigDict(extra="forbid")

    # id входит в callback_data `ws:<task hex>:<id>` ≤ 64 байт (D-28): до 28 символов, без «:».
    id: str = Field(min_length=1, max_length=28, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1)
    voice_aliases: list[str]
    gitlab_project: str = Field(min_length=1)
    default_branch: str = "main"
    test_command: str | None = None
    agent: str = "claude-code"
    # Лимит ходов агента на задачу (D-38): ограничивает расход подписки и зацикливание.
    agent_max_turns: int = Field(default=50, ge=1, le=500)


class SandboxConfig(BaseModel):
    """Песочница. В MVP — одна, созданная вручную; id выдаёт провайдер."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1)
    # Версии ставятся в песочницу bootstrap-скриптом и закреплены здесь, а не «latest» (D-38).
    claude_code_version: str = Field(default="2.1.292", pattern=_SEMVER_PATTERN)
    openspec_version: str = Field(default="1.14.3", pattern=_SEMVER_PATTERN)


class GitLabConfig(BaseModel):
    """Адрес GitLab. Токен задаётся в ENV (GITLAB_TOKEN), не здесь."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)

    @field_validator("base_url")
    @classmethod
    def _reject_userinfo(cls, value: str) -> str:
        # Учётные данные в адресе попали бы в конфиг, логи и ответы; токен задаётся только в ENV.
        # Текст ошибки не содержит значения: pydantic выводит его без input (см. _format_errors).
        parts = urlsplit(value)
        # Требуем схему http(s) и непустой netloc: без них urlsplit даёт netloc='' для строк
        # вида user:pw@host или https:/user:pw@host, и userinfo проскакивает проверку.
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("адрес должен начинаться с http:// или https:// и содержать хост")
        if "@" in parts.netloc or parts.username is not None or parts.password is not None:
            raise ValueError(
                "адрес не должен содержать учётные данные перед символом @; "
                "токен задаётся в ENV GITLAB_TOKEN"
            )
        return value


class HarnessConfig(BaseModel):
    """Корень harness.yaml."""

    model_config = ConfigDict(extra="forbid")

    workspaces: list[WorkspaceConfig] = Field(min_length=1)
    sandbox: SandboxConfig
    gitlab: GitLabConfig

    @model_validator(mode="after")
    def _check_unique_workspace_ids(self) -> Self:
        seen: set[str] = set()
        for workspace in self.workspaces:
            if workspace.id in seen:
                raise ValueError(f"повторяющийся workspace id: {workspace.id}")
            seen.add(workspace.id)
        return self


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
