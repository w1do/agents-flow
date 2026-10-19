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


class SettingsError(Exception):
    """Ошибка проверки ENV. Сообщение называет переменные, но не их значения."""


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
    novita_api_key: SecretStr | None = None
    novita_domain: str | None = None
    gitlab_url: str | None = None
    gitlab_token: SecretStr | None = None
    claude_code_oauth_token: SecretStr | None = None
    agent_run_timeout_min: int = Field(default=60, gt=0)
    tests_timeout_min: int = Field(default=15, gt=0)
    admin_email: str | None = None
    admin_password: SecretStr | None = None
    # Интервал опроса очереди worker; новая переменная mvp-02, нужна только worker.
    worker_poll_interval_sec: float = Field(default=5.0, gt=0)

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
        # Токен даёт полный операторский доступ к /tasks; короткий легко подобрать (D-23).
        # Пробелы по краям — почти всегда ошибка копирования; 32 пробела иначе прошли бы
        # проверку длины.
        if value is not None:
            raw = value.get_secret_value()
            if raw != raw.strip():
                raise ValueError("не должна начинаться или заканчиваться пробельными символами")
        if value is not None and len(value.get_secret_value()) < _ADMIN_TOKEN_MIN_LENGTH:
            raise ValueError(
                f"должна быть не короче {_ADMIN_TOKEN_MIN_LENGTH} символов (openssl rand -hex 32)"
            )
        return value

    @field_validator("telegram_webhook_secret")
    @classmethod
    def _check_webhook_secret_format(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not _WEBHOOK_SECRET_RE.fullmatch(raw) or len(raw) < _WEBHOOK_SECRET_MIN_LENGTH:
            raise ValueError(
                "допустимы только латиница, цифры, _ и -, длина от 32 до 256 (openssl rand -hex 32)"
            )
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
