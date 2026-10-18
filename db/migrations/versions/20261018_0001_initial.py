"""initial: таблицы MVP (ARCHITECTURE.md §3)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Значения CHECK записаны литералами: миграция не импортирует код приложения и не меняется
# вместе с enum. Порядок совпадает с порядком членов enum в harness_shared (D-22).


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("spec_item_id", sa.Uuid(), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("mr_url", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column(
            "tests_state",
            sa.String(length=16),
            server_default="not_run",
            nullable=False,
        ),
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
        sa.CheckConstraint("kind IN ('plan', 'implement', 'check')", name=op.f("ck_tasks_kind")),
        sa.CheckConstraint(
            "status IN ('new', 'choosing', 'planning', 'backlog', 'active', 'testing', 'ready', "
            "'merged', 'error', 'stalled', 'paused', 'trash')",
            name=op.f("ck_tasks_status"),
        ),
        sa.CheckConstraint(
            "source IN ('telegram', 'spec', 'mcp', 'api')", name=op.f("ck_tasks_source")
        ),
        sa.CheckConstraint(
            "tests_state IN ('not_run', 'passed', 'failed', 'no_tests')",
            name=op.f("ck_tasks_tests_state"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["tasks.id"],
            name=op.f("fk_tasks_parent_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index("ix_tasks_queue", "tasks", ["kind", "status", "priority", "created_at"])
    op.create_index("ix_tasks_workspace_id", "tasks", ["workspace_id"])
    op.create_index("ix_tasks_parent_id", "tasks", ["parent_id"])

    op.create_table(
        "task_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('new', 'choosing', 'planning', 'backlog', 'active', 'testing', 'ready', "
            "'merged', 'error', 'stalled', 'paused', 'trash')",
            name=op.f("ck_task_events_status"),
        ),
        sa.CheckConstraint(
            "source IN ('telegram', 'agent', 'worker', 'api')",
            name=op.f("ck_task_events_source"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_task_events_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_events")),
    )
    op.create_index("ix_task_events_task_id_created_at", "task_events", ["task_id", "created_at"])

    op.create_table(
        "routings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("command_class", sa.String(length=32), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("chosen_workspace_id", sa.String(length=64), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_routings_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routings")),
    )
    op.create_index("ix_routings_task_id", "routings", ["task_id"])

    op.create_table(
        "checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("diff_redacted", sa.Text(), nullable=True),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_checkpoints_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkpoints")),
    )
    op.create_index("ix_checkpoints_task_id", "checkpoints", ["task_id"])

    op.create_table(
        "spec_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("plan_task_id", sa.Uuid(), nullable=True),
        sa.Column("change_id", sa.String(length=128), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_checkpoint_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["last_checkpoint_id"],
            ["checkpoints.id"],
            name=op.f("fk_spec_items_last_checkpoint_id_checkpoints"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["plan_task_id"],
            ["tasks.id"],
            name=op.f("fk_spec_items_plan_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spec_items")),
        sa.UniqueConstraint(
            "workspace_id", "change_id", "key", name="uq_spec_items_workspace_change_key"
        ),
    )

    op.create_table(
        "sandboxes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.String(length=128), nullable=False),
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_task_id", sa.Uuid(), nullable=True),
        sa.Column("profile_version", sa.String(length=64), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('paused', 'active', 'error')", name=op.f("ck_sandboxes_status")
        ),
        sa.ForeignKeyConstraint(
            ["current_task_id"],
            ["tasks.id"],
            name=op.f("fk_sandboxes_current_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sandboxes")),
        sa.UniqueConstraint("provider_id", name="uq_sandboxes_provider_id"),
    )

    op.create_table(
        "task_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('planner', 'implementer')", name=op.f("ck_task_tokens_role")),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_task_tokens_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_tokens")),
        sa.UniqueConstraint("token_hash", name="uq_task_tokens_token_hash"),
    )
    op.create_index("ix_task_tokens_task_id", "task_tokens", ["task_id"])

    op.create_table(
        "telegram_messages",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "lines",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_telegram_messages_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id", name=op.f("pk_telegram_messages")),
    )

    op.create_table(
        "telegram_updates",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('update', 'callback')", name=op.f("ck_telegram_updates_kind")),
        sa.PrimaryKeyConstraint("kind", "external_id", name=op.f("pk_telegram_updates")),
    )

    # Последним: цикл tasks ↔ spec_items, FK на spec_items добавляется после создания обеих таблиц.
    op.create_foreign_key(
        op.f("fk_tasks_spec_item_id_spec_items"),
        "tasks",
        "spec_items",
        ["spec_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_tasks_spec_item_id_spec_items"), "tasks", type_="foreignkey")
    op.drop_table("telegram_updates")
    op.drop_table("telegram_messages")
    op.drop_table("task_tokens")
    op.drop_table("sandboxes")
    op.drop_table("spec_items")
    op.drop_table("checkpoints")
    op.drop_table("routings")
    op.drop_table("task_events")
    op.drop_table("tasks")
