"""Контракт миграций worker API проверяется на настоящей Postgres."""

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_worker_schema_has_event_uniqueness_heartbeat_and_recovery_state(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    try:
        async with engine.connect() as connection:
            keys, task_columns, sandbox_columns = await connection.run_sync(
                lambda conn: (
                    inspect(conn).get_unique_constraints("task_events"),
                    inspect(conn).get_columns("tasks"),
                    inspect(conn).get_columns("sandboxes"),
                )
            )
        assert any(key["column_names"] == ["task_id", "external_key"] for key in keys)
        assert "worker_heartbeat_at" in {col["name"] for col in task_columns}
        assert {"agent_launch_key", "cleanup_started", "last_released_task_id"} <= {
            col["name"] for col in sandbox_columns
        }
    finally:
        await engine.dispose()
