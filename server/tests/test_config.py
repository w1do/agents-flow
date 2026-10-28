from secrets import token_urlsafe
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError

from app.core.config import DatabaseSettings, Settings


def test_required_settings(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)
    assert {item["loc"] for item in error.value.errors()} == {("database_url",), ("jwt_secret",)}


def test_alembic_reads_database_url_from_standard_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    database_path = tmp_path / "migration.db"
    env_file.write_text(f"DATABASE_URL=sqlite+pysqlite:///{database_path}\n", encoding="utf-8")
    monkeypatch.setitem(DatabaseSettings.model_config, "env_file", env_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    assert database_path.is_file()


def test_secrets_are_hidden_and_integrations_optional(monkeypatch):
    secret = token_urlsafe(32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", secret)
    monkeypatch.setenv("ADMIN_PASSWORD", secret)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    settings = Settings(_env_file=None)
    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()
    assert settings.telegram_bot_token.get_secret_value() == ""
    assert settings.transcription_provider == "stub"
    assert settings.agent_provider == "stub"


def test_jwt_secret_requires_32_bytes():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite://", jwt_secret="s" * 31)


def test_jwt_secret_counts_utf8_bytes():
    settings = Settings(_env_file=None, database_url="sqlite://", jwt_secret="💩" * 8)
    assert len(settings.jwt_secret.get_secret_value().encode("utf-8")) == 32


def test_trusted_proxy_ips_default_and_environment(monkeypatch):
    defaults = Settings(_env_file=None, database_url="sqlite://", jwt_secret="s" * 32)
    assert defaults.trusted_proxy_ips == []
    monkeypatch.setenv("TRUSTED_PROXY_IPS", '["127.0.0.1", "10.0.0.2"]')
    configured = Settings(_env_file=None, database_url="sqlite://", jwt_secret="s" * 32)
    assert configured.trusted_proxy_ips == ["127.0.0.1", "10.0.0.2"]


@pytest.mark.parametrize("value", ["garbage", "*"])
def test_trusted_proxy_ips_rejects_invalid_network(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite://", jwt_secret="s" * 32,
                 trusted_proxy_ips=[value])
