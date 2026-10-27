from uuid import UUID

from sqlalchemy import func, select

from app.models.agent import Agent
from app.models.project import Project
from app.models.task import Task
from app.repositories.base import Repository


class ProjectRepository(Repository[Project]):
    model = Project

    def with_counts(self, project_id: UUID | None = None, offset: int = 0,
                    limit: int = 50) -> list[tuple[Project, int, int]]:
        active_tasks = select(func.count(Task.id)).where(
            Task.project_id == Project.id,
            Task.status.in_(("choosing", "planning", "active", "testing")),
        ).correlate(Project).scalar_subquery()
        agents = select(func.count(Agent.id)).where(
            Agent.project_id == Project.id,
        ).correlate(Project).scalar_subquery()
        statement = select(Project, active_tasks, agents).order_by(Project.created_at, Project.id)
        if project_id is not None:
            statement = statement.where(Project.id == project_id)
        else:
            statement = statement.offset(offset).limit(limit)
        return [(project, tasks, agents) for project, tasks, agents in self.session.execute(statement)]
