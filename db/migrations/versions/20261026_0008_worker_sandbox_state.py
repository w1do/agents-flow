"""Ключ запуска и фаза очистки для восстановления удалённого worker."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sandboxes", sa.Column("last_released_task_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sandboxes_last_released_task",
        "sandboxes",
        "tasks",
        ["last_released_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("sandboxes", sa.Column("agent_launch_key", sa.String(128), nullable=True))
    op.add_column(
        "sandboxes",
        sa.Column("cleanup_started", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_constraint("fk_sandboxes_last_released_task", "sandboxes", type_="foreignkey")
    op.drop_column("sandboxes", "last_released_task_id")
    op.drop_column("sandboxes", "cleanup_started")
    op.drop_column("sandboxes", "agent_launch_key")
