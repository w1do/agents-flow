"""sandboxes: время запуска и pid агента на сервере (mvp-06, D-41)."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable без server_default: у существующих песочниц агент не запущен, значения NULL верны.
    op.add_column(
        "sandboxes", sa.Column("agent_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("sandboxes", sa.Column("agent_pid", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("sandboxes", "agent_pid")
    op.drop_column("sandboxes", "agent_started_at")
