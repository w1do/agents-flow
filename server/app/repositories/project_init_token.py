from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from app.models.project_init_token import ProjectInitToken
from app.repositories.base import Repository


class ProjectInitTokenRepository(Repository[ProjectInitToken]):
    model = ProjectInitToken

    def by_hash(self, token_hash: str) -> ProjectInitToken | None:
        return self.session.scalar(select(ProjectInitToken).where(
            ProjectInitToken.token_hash == token_hash,
        ))

    def mark_used(self, token_id: UUID, now: datetime) -> bool:
        # The conditional UPDATE also prevents two concurrent consumers succeeding.
        statement = update(ProjectInitToken).where(
            ProjectInitToken.id == token_id, ProjectInitToken.used_at.is_(None),
            ProjectInitToken.expires_at > now,
        ).values(used_at=now).returning(ProjectInitToken.id).execution_options(
            synchronize_session="fetch",
        )
        return self.session.execute(statement).scalar_one_or_none() is not None

    def latest_unused_expiry(self, project_id: UUID, now: datetime) -> datetime | None:
        return self.session.scalar(select(ProjectInitToken.expires_at).where(
            ProjectInitToken.project_id == project_id,
            ProjectInitToken.used_at.is_(None), ProjectInitToken.expires_at > now,
        ).order_by(ProjectInitToken.expires_at.desc()).limit(1))
