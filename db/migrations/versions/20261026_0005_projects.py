"""projects: каталог проектов на сервере (openspec change project-setup-via-flow, D-65)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Значения CHECK записаны литералами: миграция не импортирует код приложения.


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=28), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "voice_aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("repo_provider", sa.String(length=16), nullable=False),
        sa.Column("repo_base_url", sa.String(length=255), nullable=False),
        sa.Column("repo_project", sa.String(length=255), nullable=False),
        sa.Column("access_ref", sa.String(length=255), nullable=True),
        sa.Column("default_branch", sa.String(length=128), server_default="main", nullable=False),
        sa.Column("test_command", sa.Text(), nullable=True),
        sa.Column("agent", sa.String(length=32), nullable=False),
        sa.Column("agent_max_turns", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f("ck_projects_status")),
        sa.CheckConstraint(
            "repo_provider IN ('github', 'gitlab')", name=op.f("ck_projects_repo_provider")
        ),
        sa.CheckConstraint(
            "access_ref IS NULL OR access_ref LIKE 'vault:%'",
            name=op.f("ck_projects_access_ref"),
        ),
        sa.CheckConstraint("agent_max_turns > 0", name=op.f("ck_projects_agent_max_turns")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )


def downgrade() -> None:
    op.drop_table("projects")
