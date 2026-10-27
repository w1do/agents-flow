from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
import sqlalchemy as sa

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


def test_existing_skill_snapshot_keeps_missing_content_explicit(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'populated-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("JWT_SECRET", token_urlsafe(32))
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_engine(url)
    project_id, category_id, skill_id, task_id, snapshot_id = [uuid4() for _ in range(5)]
    try:
        command.upgrade(config, "0001")
        with engine.begin() as connection:
            connection.execute(sa.text("INSERT INTO projects (id, name) VALUES (:id, 'P')"),
                               {"id": project_id.hex})
            connection.execute(sa.text("INSERT INTO skill_categories (id, name, description) "
                                       "VALUES (:id, 'Build', '')"), {"id": category_id.hex})
            connection.execute(sa.text("INSERT INTO skills "
                "(id, category_id, name, description, content, content_hash) "
                "VALUES (:id, :category, 'Skill', '', 'Version 2', 'hash-v2')"),
                {"id": skill_id.hex, "category": category_id.hex})
            connection.execute(sa.text("INSERT INTO tasks "
                "(id, project_id, title, description, source_type, source_text) "
                "VALUES (:id, :project, 'Task', '', 'api', '')"),
                {"id": task_id.hex, "project": project_id.hex})
            connection.execute(sa.text("INSERT INTO task_skill_snapshots "
                "(id, task_id, skill_id, skill_name, skill_version, content_hash) "
                "VALUES (:id, :task, :skill, 'Skill', 1, 'hash-v1')"),
                {"id": snapshot_id.hex, "task": task_id.hex, "skill": skill_id.hex})
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(sa.text("SELECT skill_version, content_hash, content, "
                "content_missing FROM task_skill_snapshots WHERE id = :id"),
                {"id": snapshot_id.hex}).one()
            assert tuple(row) == (1, "hash-v1", "", True)
    finally:
        engine.dispose()
        get_settings.cache_clear()
