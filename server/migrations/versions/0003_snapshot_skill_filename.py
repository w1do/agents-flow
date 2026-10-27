"""Keep skill filenames stable when restoring a task snapshot."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_skill_snapshots", sa.Column("filename", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_skill_snapshots", "filename")
