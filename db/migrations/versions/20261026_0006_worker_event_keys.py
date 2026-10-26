"""Идемпотентность отчётов worker по паре task_id, external_key."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_events", sa.Column("external_key", sa.String(128), nullable=True))
    op.create_unique_constraint(
        "uq_task_events_external_key", "task_events", ["task_id", "external_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_task_events_external_key", "task_events", type_="unique")
    op.drop_column("task_events", "external_key")
