"""Настройки процесса из ENV: адреса и секреты. Несекретные настройки workspace — в config.py.

Секреты объявлены как SecretStr, чтобы не попасть в repr, лог или вывод ошибки.
Пустая переменная считается отсутствующей (env_ignore_empty), иначе пустой токен прошёл бы проверку.
"""

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Telegram принимает secret_token только из этих символов и длиной до 256.
_WEBHOOK_SECRET_RE = re.compile(r"[A-Za-z0-9_-]{1,256}")
# Короче 32 символов секрет легко подобрать перебором: минимум как у HARNESS_SECRET_KEY (D-29).
_WEBHOOK_SECRET_MIN_LENGTH = 32
_SECRET_KEY_MIN_LENGTH = 32
_ADMIN_TOKEN_MIN_LENGTH = 32
# id личного чата владельца положительный. Группы (отрицательный id) не поддерживаются: авторизация
# идёт по chat_id, и любой участник группы мог бы создавать задачи (D-30).
_CHAT_ID_RE = re.compile(r"\d+")
# Лимит getFile Telegram: больший файл бот не скачает, поэтому выше значения не принимается.
_VOICE_MAX_BYTES_LIMIT = 20 * 1024 * 1024


# Пробельные, управляющие и не-ASCII символы в адресе не допускаются: строка с переносом или
# пробелом разбирается по-разному у разных клиентов.
_URL_FORBIDDEN_RE = re.compile(r"[\s\x00-\x1f\x7f]|[^\x00-\x7f]")
_HTTPS_URL_MESSAGE = (
    "должен начинаться с https:// (строчными), без пробелов и управляющих символов, "
    "учётных данных, query и fragment, с непустым хостом и портом 1–65535 (D-61)"
)


def _check_https_base_url(value: str) -> None:
    """Проверка адреса, через который уходит токен бота или приходит webhook (D-61).

    Текст ошибки не содержит значения: адрес прокси владельца в логи не попадает.
    """
    if _URL_FORBIDDEN_RE.search(value) or not value.startswith("https://"):
        raise ValueError(_HTTPS_URL_MESSAGE)
    parts = urlsplit(value)
    if "@" in parts.netloc or parts.query or parts.fragment or "?" in value or "#" in value:
        raise ValueError(_HTTPS_URL_MESSAGE)
    if not parts.hostname:
        raise ValueError(_HTTPS_URL_MESSAGE)
    try:
        _ = parts.port  # порт вне 0–65535 или нечисловой: urllib бросает ValueError
    except ValueError:
        raise ValueError(_HTTPS_URL_MESSAGE) from None


class SettingsError(Exception):
    """Ошибка проверки ENV. Сообщение называет переменные, но не их значения."""


def _check_admin_token(value: SecretStr | None) -> SecretStr | None:
    """Токен даёт полный операторский доступ к /tasks и каталогу проектов; короткий легко подобрать.

    Пробелы по краям — почти всегда ошибка копирования; 32 пробела иначе прошли бы проверку длины.
    Сообщение не содержит значения токена.
    """
    if value is not None:
        raw = value.get_secret_value()
        if raw != raw.strip():
            raise ValueError("не должна начинаться или заканчиваться пробельными символами")
        if len(raw) < _ADMIN_TOKEN_MIN_LENGTH:
            raise ValueError(
                f"должна быть не короче {_ADMIN_TOKEN_MIN_LENGTH} символов (openssl rand -hex 32)"
            )
    return value


class Settings(BaseSettings):
    """Переменные из ARCHITECTURE.md §9.

    Обязательные — ядро и Telegram (решение mvp-02). Остальные опциональны, пока их не использует
    свой этап; их появление фиксируется в .env.example и ARCHITECTURE.md §9.
    """

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, env_ignore_empty=True)

    database_url: SecretStr
    harness_config: Path
    harness_secret_key: SecretStr
    telegram_bot_token: SecretStr
    telegram_chat_id: str
    telegram_webhook_secret: SecretStr
    # Адрес Bot API: прокси владельца, если прод-сервер не достаёт api.telegram.org (D-61).
    telegram_api_url: str = "https://api.telegram.org"
    # Адрес, куда Telegram шлёт апдейты (прокси владельца). Пусто = HARNESS_PUBLIC_URL (D-61).
    telegram_webhook_url: str | None = None

    harness_public_url: str | None = None
    harness_admin_token: SecretStr | None = None
    polza_ai_url: str | None = None
    polza_ai_key: SecretStr | None = None
    polza_ai_model: str | None = None
    # ниже порога — кнопки уточнения (D-33).
    routing_min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    # OpenAI-совместимый протокол; Whisper через Polza. Других провайдеров пока нет.
    stt_provider: Literal["openai"] | None = None
    stt_api_url: str | None = None
    stt_api_key: SecretStr | None = None
    stt_model: str | None = None
    # Лимит размера голосового файла: лимит getFile Telegram; ENV VOICE_MAX_BYTES.
    voice_max_bytes: int = Field(default=_VOICE_MAX_BYTES_LIMIT, gt=0, le=_VOICE_MAX_BYTES_LIMIT)
    claude_code_oauth_token: SecretStr | None = None
    agent_run_timeout_min: int = Field(default=60, gt=0)
    tests_timeout_min: int = Field(default=15, gt=0)
    admin_email: str | None = None
    admin_password: SecretStr | None = None
    # Интервал опроса очереди worker; новая переменная mvp-02, нужна только worker.
    worker_poll_interval_sec: float = Field(default=5.0, gt=0)
    # Интервал опроса агента в песочнице (mvp-06, D-38): реже очереди, агент работает минуты.
    agent_poll_interval_sec: float = Field(default=15.0, gt=0)
    # Vault с ключами владельца (D-45): MCP-сервер по Streamable HTTP. Оба поля нужны вместе.
    vault_mcp_url: str | None = None
    vault_mcp_token: SecretStr | None = None

    @field_validator("harness_secret_key")
    @classmethod
    def _check_secret_key_length(cls, value: SecretStr) -> SecretStr:
        # Короткий ключ легко подобрать, поэтому минимальная длина фиксирована. Значение в текст
        # ошибки не выводится: pydantic покажет только имя поля и правило.
        if len(value.get_secret_value()) < _SECRET_KEY_MIN_LENGTH:
            raise ValueError(
                f"должна быть не короче {_SECRET_KEY_MIN_LENGTH} символов (openssl rand -hex 32)"
            )
        return value

    @field_validator("harness_admin_token")
    @classmethod
    def _check_admin_token_length(cls, value: SecretStr | None) -> SecretStr | None:
        return _check_admin_token(value)

    @field_validator("telegram_webhook_secret")
    @classmethod
    def _check_webhook_secret_format(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not _WEBHOOK_SECRET_RE.fullmatch(raw) or len(raw) < _WEBHOOK_SECRET_MIN_LENGTH:
            raise ValueError(
                "допустимы только латиница, цифры, _ и -, длина от 32 до 256 (openssl rand -hex 32)"
            )
        return value

    @field_validator("telegram_api_url")
    @classmethod
    def _check_telegram_api_url(cls, value: str) -> str:
        # Токен бота стоит в пути URL: открытый http его раскроет (D-61). Слеш в конце убираем,
        # чтобы клиент не склеивал «//bot…».
        _check_https_base_url(value)
        return value.rstrip("/")

    @field_validator("telegram_webhook_url")
    @classmethod
    def _check_telegram_webhook_url(cls, value: str | None) -> str | None:
        # Апдейты приходят с секретом webhook: адрес тоже только https (D-61).
        if value is not None:
            _check_https_base_url(value)
        return value

    @field_validator("telegram_chat_id")
    @classmethod
    def _check_chat_id(cls, value: str) -> str:
        # Значение в текст ошибки не выводится: это id чата владельца (D-30).
        if not _CHAT_ID_RE.fullmatch(value) or int(value) <= 0:
            raise ValueError(
                "должен быть положительным числовым id личного чата владельца "
                "(групповые чаты не поддерживаются, D-30)"
            )
        return value

    @field_validator("polza_ai_url")
    @classmethod
    def _check_polza_ai_url(cls, value: str | None) -> str | None:
        # Текст владельца уходит во внешний сервис: только https, как у STT (D-31).
        if value is not None and urlsplit(value).scheme != "https":
            raise ValueError("должен начинаться с https://")
        return value

    @field_validator("vault_mcp_url")
    @classmethod
    def _check_vault_mcp_url(cls, value: str | None) -> str | None:
        # Токен vault и ответы с секретами не должны уходить по открытому каналу (D-45).
        if value is not None and urlsplit(value).scheme != "https":
            raise ValueError("должен начинаться с https://")
        return value

    @field_validator("stt_api_url")
    @classmethod
    def _check_stt_api_url(cls, value: str | None) -> str | None:
        # Аудио с голосом владельца не должно уходить по открытому каналу (D-29, S6).
        if value is not None and urlsplit(value).scheme != "https":
            raise ValueError("должен начинаться с https://")
        return value


def load_settings() -> Settings:
    """Читает ENV и возвращает проверенные настройки.

    Бросает SettingsError с именами переменных. Текст pydantic-ошибки не используется целиком,
    потому что он содержит введённые значения (секреты).
    """
    try:
        # mypy не видит, что обязательные поля берутся из ENV, и требует их как аргументы.
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in err['loc']).upper()}: {err['msg']}"
            for err in exc.errors(include_url=False, include_input=False, include_context=False)
        )
        raise SettingsError(f"некорректные ENV: {details}") from None


class AgentSettings(BaseSettings):
    """Minimal operator environment for agent init; it never loads .env."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", env_ignore_empty=True)
    harness_config: Path
    vault_mcp_url: str | None = None
    vault_mcp_token: SecretStr | None = None
    harness_public_url: str | None = None
    # Операторский токен для запроса настроек проекта у сервера (project-catalog, D-23).
    harness_admin_token: SecretStr | None = None

    @field_validator("harness_admin_token")
    @classmethod
    def _check_admin_token_length(cls, value: SecretStr | None) -> SecretStr | None:
        return _check_admin_token(value)
