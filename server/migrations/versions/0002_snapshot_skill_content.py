"""Store immutable skill contents and categories in task snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_skill_snapshots", sa.Column(
        "category", sa.Text(), nullable=False, server_default=""))
    op.add_column("task_skill_snapshots", sa.Column(
        "content", sa.Text(), nullable=False, server_default=""))
    op.execute(sa.text("""
        UPDATE task_skill_snapshots
        SET category = (SELECT skill_categories.name FROM skills
                        JOIN skill_categories ON skills.category_id = skill_categories.id
                        WHERE skills.id = task_skill_snapshots.skill_id),
            content = (SELECT skills.content FROM skills
                       WHERE skills.id = task_skill_snapshots.skill_id)
    """))
    with op.batch_alter_table("task_skill_snapshots") as batch:
        batch.alter_column("category", server_default=None)
        batch.alter_column("content", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("task_skill_snapshots") as batch:
        batch.drop_column("content")
        batch.drop_column("category")
