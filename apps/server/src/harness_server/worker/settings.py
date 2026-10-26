"""Минимальные ENV машины worker: без DATABASE_URL, ключа сервера и Telegram."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from harness_server.settings import SettingsError, _check_admin_token, _check_https_base_url


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True, env_file=None)
    harness_config: Path
    harness_public_url: str
    worker_api_token: SecretStr
    claude_code_oauth_token: SecretStr | None = None
    worker_poll_interval_sec: float = Field(default=5.0, gt=0)
    agent_poll_interval_sec: float = Field(default=15.0, gt=0)
    agent_run_timeout_min: int = Field(default=60, gt=0)
    vault_mcp_url: str | None = None
    vault_mcp_token: SecretStr | None = None

    @field_validator("worker_api_token")
    @classmethod
    def _token(cls, value: SecretStr) -> SecretStr:
        _check_admin_token(value)
        return value

    @field_validator("harness_public_url")
    @classmethod
    def _url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"}:
            _check_https_base_url("https://" + value.removeprefix("http://"))
        else:
            _check_https_base_url(value)
        return value.rstrip("/")


def load_worker_settings() -> WorkerSettings:
    """Безопасная диагностика: только имена неверных ENV, без их значений."""
    try:
        # BaseSettings читает обязательные поля из ENV, mypy этого не видит.
        return WorkerSettings()  # type: ignore[call-arg]
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]).upper() for e in exc.errors(include_input=False)})
        raise SettingsError("некорректные ENV worker: " + ", ".join(fields)) from None
