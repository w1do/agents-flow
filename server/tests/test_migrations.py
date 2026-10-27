from pathlib import Path
from secrets import token_urlsafe

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings
from app.models import Base


def test_migration_round_trip_matches_models(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("JWT_SECRET", token_urlsafe(32))
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_server_default": True})
            assert compare_metadata(context, Base.metadata) == []
        command.downgrade(config, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()
        get_settings.cache_clear()
