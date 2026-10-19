"""routings: решение без задачи, уточнение кнопкой, причина запасного пути (mvp-05, D-32)."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("routings", "task_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column(
        "routings",
        "command_class",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    # server_default нужен только для добавления колонки: строк до mvp-05 в routings нет.
    op.add_column(
        "routings",
        sa.Column("decision", sa.String(length=16), nullable=False, server_default="fallback"),
    )
    op.alter_column("routings", "decision", server_default=None)
    op.add_column("routings", sa.Column("error", sa.String(length=64), nullable=True))
    op.add_column("routings", sa.Column("source_text", sa.Text(), nullable=True))
    op.add_column("routings", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_routings_command_class"),
        "routings",
        "command_class IN ('work', 'status', 'unknown')",
    )
    op.create_check_constraint(
        op.f("ck_routings_decision"),
        "routings",
        "decision IN ('auto', 'clarify', 'fallback')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_routings_decision"), "routings", type_="check")
    op.drop_constraint(op.f("ck_routings_command_class"), "routings", type_="check")
    op.drop_column("routings", "resolved_at")
    op.drop_column("routings", "source_text")
    op.drop_column("routings", "error")
    op.drop_column("routings", "decision")
    op.alter_column(
        "routings",
        "command_class",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    # При NOT NULL строки без задачи не сохранить: откат удаляет решения status/unknown/уточнения.
    op.execute("DELETE FROM routings WHERE task_id IS NULL")
    op.alter_column("routings", "task_id", existing_type=sa.Uuid(), nullable=False)
