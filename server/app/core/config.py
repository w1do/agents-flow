from functools import lru_cache
import ipaddress
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: str = Field(min_length=1, repr=False)
    jwt_secret: SecretStr
    admin_email: str | None = None
    admin_password: SecretStr | None = None
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_webhook_secret: SecretStr | None = None
    transcription_provider: str = "stub"
    transcription_api_key: SecretStr | None = None
    transcription_model: str = "whisper-1"
    public_base_url: str = "http://localhost:8000"
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    agent_provider: str = "stub"
    agent_model: str | None = None
    lease_ttl_seconds: int = Field(default=60, gt=0)
    poll_interval_seconds: int = Field(default=5, gt=0)

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_has_32_bytes(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 bytes")
        return value

    @field_validator("trusted_proxy_ips")
    @classmethod
    def trusted_proxy_ips_are_networks(cls, values: list[str]) -> list[str]:
        for value in values:
            if value == "*":
                raise ValueError("TRUSTED_PROXY_IPS must not contain '*'")
            try:
                ipaddress.ip_network(value, strict=False)
            except ValueError as error:
                raise ValueError("TRUSTED_PROXY_IPS must contain only valid IPs or CIDRs") from error
        return values


class DatabaseSettings(BaseSettings):
    """Migration database configuration, independent of application JWT settings."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
        extra="ignore",
    )

    database_url: str = Field(min_length=1, repr=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
