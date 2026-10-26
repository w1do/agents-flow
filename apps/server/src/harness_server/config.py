"""Загрузка и проверка config/harness.yaml: глобальные настройки сервера и песочницы.

Проекты (workspace) в файл не пишутся: они хранятся на сервере и заводятся в консоли или через
API (project-catalog, D-65). Старая форма с блоком workspaces или секцией gitlab отклоняется
с подсказкой.

Секреты в YAML запрещены: ключи с сегментами token/tokens/key/password/passwd/pwd/secret/secrets/
apikey/credential/credentials отклоняются до валидации Pydantic (D-20, D-26). Ошибки называют путь к
полю, но не значение.
"""

import re
from pathlib import Path
from typing import Any

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

_MOVED_WORKSPACES: str = (
    "блок workspaces удалён: проекты заводятся на сервере (консоль или API "
    "/api/console/projects), перенесите его по docs/deployment.md"
)
_MOVED_GITLAB: str = (
    "секция gitlab удалена (D-60): адрес, проект и ключ задаются у проекта на сервере "
    "(repo: provider, project, access_ref)"
)


class SandboxMemoryConfig(BaseModel):
    """Память проекта на машине агента. Нет блока — память выключена."""

    model_config = ConfigDict(extra="forbid")

    # Ключ embeddings — только ссылка vault:…; без неё поиск лексический.
    embedding_ref: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_removed_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field in ("repo", "ref"):
                if field in data:
                    raise ValueError(
                        f"sandbox.memory.{field} удалён: версии и установка — на машине владельца"
                    )
        return data

    @field_validator("embedding_ref")
    @classmethod
    def _check_embedding_ref(cls, value: str | None) -> str | None:
        return _check_vault_ref(value, "embedding_ref")


# Автор коммитов: без управляющих символов (в том числе перевода строки); адрес без @ и пробелов.
_GIT_NAME_PATTERN = r"^[^\x00-\x1f\x7f]+$"
_GIT_EMAIL_PATTERN = r"^[^@\s\x00-\x1f\x7f]+@[^@\s\x00-\x1f\x7f]+$"


class GitAuthorConfig(BaseModel):
    """Автор коммитов агента, передаваемый только через env процесса."""

    model_config = ConfigDict(extra="forbid")

    # Без управляющих символов и перевода строки: значение идёт в env git-процесса.
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

    @model_validator(mode="before")
    @classmethod
    def _reject_removed_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field in ("claude_code_version", "openspec_version"):
                if field in data:
                    raise ValueError(
                        f"sandbox.{field} удалён: версии и установка — на машине владельца"
                    )
        return data

    memory: SandboxMemoryConfig | None = None
    git_author: GitAuthorConfig = Field(default_factory=GitAuthorConfig)


class HarnessConfig(BaseModel):
    """Корень harness.yaml: глобальные настройки сервера и песочницы (D-65)."""

    model_config = ConfigDict(extra="forbid")

    sandbox: SandboxConfig

    @model_validator(mode="before")
    @classmethod
    def _reject_moved_sections(cls, data: Any) -> Any:
        # Блоки переехали на сервер: без подсказки extra=forbid дал бы безликое «не разрешено».
        if isinstance(data, dict):
            if "workspaces" in data:
                raise ValueError(_MOVED_WORKSPACES)
            if "gitlab" in data:
                raise ValueError(_MOVED_GITLAB)
        return data


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
