"""Проекты (workspace) на сервере: каталог, который заводит оператор (project-catalog, D-65)."""

from typing import Any

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from harness_server.db.base import Base, TimestampMixin


class Project(TimestampMixin, Base):
    """Проект, с которым работает харнесс. Блок repo разложен по колонкам repo_*.

    access_ref — только ссылка на vault (vault:<project>/<service>/<name>), NULL — анонимный клон.
    Значение ключа сюда не попадает: его не хранит ни одна таблица.
    """

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
        CheckConstraint("repo_provider IN ('github', 'gitlab')", name="repo_provider"),
        CheckConstraint("access_ref IS NULL OR access_ref LIKE 'vault:%'", name="access_ref"),
        CheckConstraint("agent_max_turns > 0", name="agent_max_turns"),
    )

    id: Mapped[str] = mapped_column(String(28), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    voice_aliases: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb", default=list
    )
    repo_provider: Mapped[str] = mapped_column(String(16), nullable=False)
    repo_base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_project: Mapped[str] = mapped_column(String(255), nullable=False)
    access_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_branch: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="main", default="main"
    )
    test_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent: Mapped[str] = mapped_column(String(32), nullable=False, default="claude-code")
    agent_max_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active", default="active"
    )

    @property
    def repo(self) -> dict[str, Any]:
        """Блок repo в форме ProjectRepo: сервис читает проект через Pydantic, а не по колонкам."""
        return {
            "provider": self.repo_provider,
            "base_url": self.repo_base_url,
            "project": self.repo_project,
            "access_ref": self.access_ref,
        }
