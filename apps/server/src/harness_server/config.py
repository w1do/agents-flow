"""Загрузка и проверка config/harness.yaml: несекретные настройки workspace, sandbox, gitlab.

Секреты в YAML запрещены: ключи с сегментами token/key/password/secret/apikey отклоняются
до валидации Pydantic. Ошибки называют путь к полю (workspaces[0].gitlab_token), но не значение.
"""

import re
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(Exception):
    """Ошибка harness.yaml. Сообщение содержит путь к полю, но не значения."""


_SECRET_SEGMENTS = frozenset({"token", "key", "password", "secret", "apikey"})
_SEGMENT_SPLIT = re.compile(r"[_-]")
# Граница camelCase: accessToken → access_Token, чтобы сегмент token не терялся внутри слова.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class WorkspaceConfig(BaseModel):
    """Проект, с которым работает харнесс: GitLab-репозиторий и команда тестов."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    voice_aliases: list[str]
    gitlab_project: str = Field(min_length=1)
    default_branch: str = "main"
    test_command: str | None = None
    agent: str = "claude-code"


class SandboxConfig(BaseModel):
    """Песочница. В MVP — одна, созданная вручную; id выдаёт провайдер."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1)


class GitLabConfig(BaseModel):
    """Адрес GitLab. Токен задаётся в ENV (GITLAB_TOKEN), не здесь."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)


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
