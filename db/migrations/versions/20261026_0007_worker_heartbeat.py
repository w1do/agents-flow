"""Последний heartbeat задачи; NULL сохраняет прежнюю очередь без worker API."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks", sa.Column("worker_heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tasks", "worker_heartbeat_at")
