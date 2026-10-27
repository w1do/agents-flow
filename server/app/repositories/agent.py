from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.repositories.base import Repository


class AgentRepository(Repository[Agent]):
    model = Agent

    def by_token_hash(self, token_hash: str) -> Agent | None:
        return self.session.scalar(select(Agent).where(Agent.agent_token_hash == token_hash))

    def by_name(self, project_id: UUID, name: str) -> Agent | None:
        return self.session.scalar(select(Agent).where(
            Agent.project_id == project_id, Agent.name == name,
        ))

    def get_for_project(self, agent_id: UUID, project_id: UUID) -> Agent | None:
        return self.session.scalar(select(Agent).where(
            Agent.id == agent_id, Agent.project_id == project_id,
        ))

    def for_project(self, project_id: UUID, offset: int = 0, limit: int = 50) -> list[Agent]:
        return list(self.session.scalars(select(Agent).where(
            Agent.project_id == project_id,
        ).order_by(Agent.created_at, Agent.id).offset(offset).limit(limit)))

    def lock(self, agent_id: UUID) -> Agent | None:
        return self.session.scalar(select(Agent).where(Agent.id == agent_id).with_for_update()
                                   .execution_options(populate_existing=True))


def get_for_project(session: Session, agent_id: UUID, project_id: UUID) -> Agent | None:
    return AgentRepository(session).get_for_project(agent_id, project_id)
