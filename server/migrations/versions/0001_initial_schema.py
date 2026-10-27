"""Полная начальная схема Agents Flow."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None
JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def identity():
    return sa.Column("id", sa.Uuid(), primary_key=True, nullable=False)


def timestamp(name, *, nullable=False, default=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if default else None)


def foreign_key(name, target, *, nullable=False):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target), nullable=nullable)


def text(name, *, nullable=False, default=None):
    return sa.Column(name, sa.Text(), nullable=nullable, server_default=default)


def upgrade() -> None:
    op.create_table("users", identity(), text("email"), text("password_hash"),
                    timestamp("created_at"), sa.UniqueConstraint("email"))
    op.create_table("projects", identity(), text("name"),
                    text("description", nullable=True), text("telegram_chat_id", nullable=True),
                    text("project_token_hash", nullable=True),
                    timestamp("created_at"), timestamp("updated_at"))
    op.create_table("project_init_tokens", identity(), foreign_key("project_id", "projects.id"),
                    text("token_hash"), timestamp("expires_at", default=False),
                    timestamp("used_at", nullable=True, default=False), timestamp("created_at"))
    op.create_table("agents", identity(), foreign_key("project_id", "projects.id"),
                    text("name"), text("agent_token_hash"), text("repository_path_hint"),
                    text("git_remote"), text("status", default="offline"),
                    timestamp("last_heartbeat_at", nullable=True, default=False),
                    timestamp("created_at"), timestamp("updated_at"),
                    sa.UniqueConstraint("project_id", "name"),
                    sa.CheckConstraint("status IN ('online', 'busy', 'offline')", name="status"))
    op.create_table("skill_categories", identity(), text("name"), text("description"),
                    sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("skills", identity(), foreign_key("category_id", "skill_categories.id"),
                    text("name"), text("description"), text("content"), text("content_hash"),
                    sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
                    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
                    timestamp("created_at"), timestamp("updated_at"))
    op.create_table("agent_skills", identity(), foreign_key("agent_id", "agents.id"),
                    foreign_key("skill_id", "skills.id"), timestamp("assigned_at"),
                    sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
                    sa.UniqueConstraint("agent_id", "skill_id"))
    op.create_table("tasks", identity(), foreign_key("project_id", "projects.id"),
                    text("title"), text("description"), text("source_type"), text("source_text"),
                    text("status", default="new"),
                    foreign_key("assigned_agent_id", "agents.id", nullable=True),
                    sa.Column("lease_id", sa.Uuid(), nullable=True),
                    timestamp("lease_expires_at", nullable=True, default=False),
                    text("plan_text", nullable=True),
                    sa.Column("plan_revision", sa.Integer(), nullable=False, server_default="0"),
                    text("plan_decision", default="pending"), text("plan_feedback", nullable=True),
                    text("result_summary", nullable=True),
                    sa.Column("result_data", JSON_VALUE, nullable=True),
                    sa.Column("checkpoint", JSON_VALUE, nullable=True),
                    timestamp("created_at"), timestamp("updated_at"),
                    timestamp("completed_at", nullable=True, default=False),
                    sa.CheckConstraint(
                        "status IN ('new', 'choosing', 'planning', 'backlog', 'active', 'testing', "
                        "'ready', 'merged', 'error', 'stalled', 'paused', 'trash')", name="status"),
                    sa.CheckConstraint(
                        "source_type IN ('web', 'telegram_text', 'telegram_voice', 'api')",
                        name="source_type"),
                    sa.CheckConstraint("plan_decision IN ('pending', 'approved', 'rejected')",
                                       name="plan_decision"))
    op.create_table("task_skill_snapshots", identity(), foreign_key("task_id", "tasks.id"),
                    foreign_key("skill_id", "skills.id"), text("skill_name"),
                    sa.Column("skill_version", sa.Integer(), nullable=False), text("content_hash"),
                    sa.UniqueConstraint("task_id", "skill_id"))
    op.create_table("task_events", identity(), foreign_key("task_id", "tasks.id"),
                    foreign_key("agent_id", "agents.id", nullable=True),
                    text("event_id", nullable=True), text("event_type"), text("message"),
                    sa.Column("payload", JSON_VALUE, nullable=True), timestamp("created_at"),
                    sa.UniqueConstraint("task_id", "event_id"))
    op.create_table("idempotency_keys", identity(), text("scope"), text("idempotency_key"),
                    text("request_hash"), sa.Column("response_code", sa.Integer(), nullable=False),
                    sa.Column("response_body", JSON_VALUE, nullable=False), timestamp("created_at"),
                    sa.UniqueConstraint("scope", "idempotency_key"))
    op.create_index("ix_tasks_project_id_status", "tasks", ["project_id", "status"])
    op.create_index("ix_tasks_status_created_at", "tasks", ["status", "created_at"])
    op.create_index("ix_task_events_task_id_created_at", "task_events", ["task_id", "created_at"])
    op.create_index("ix_agent_skills_agent_id", "agent_skills", ["agent_id"])


def downgrade() -> None:
    for name in ("idempotency_keys", "task_events", "task_skill_snapshots", "tasks",
                 "agent_skills", "skills", "skill_categories", "agents", "project_init_tokens",
                 "projects", "users"):
        op.drop_table(name)
