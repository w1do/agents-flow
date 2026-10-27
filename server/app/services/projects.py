from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.core.time import LEASE_TTL_SECONDS, as_utc
from app.models.project import Project
from app.repositories.agent import AgentRepository, get_for_project
from app.repositories.project import ProjectRepository
from app.repositories.project_init_token import ProjectInitTokenRepository
from app.schemas.projects import (
    AgentSummary, InitTokenResponse, ProjectCard, ProjectCreate, ProjectSummary,
)
from app.services.init_tokens import issue_init_token


def get_project(session: Session, project_id: UUID) -> Project:
    project = ProjectRepository(session).get(project_id)
    if project is None:
        raise not_found()
    return project


def get_agent_for_project(session: Session, agent_id: UUID, project_id: UUID):
    return get_for_project(session, agent_id, project_id)


def _agent_summary(agent, now: datetime) -> AgentSummary:
    heartbeat = as_utc(agent.last_heartbeat_at) if agent.last_heartbeat_at else None
    cutoff = now - timedelta(seconds=2 * LEASE_TTL_SECONDS)
    status = agent.status if heartbeat and heartbeat >= cutoff else "offline"
    return AgentSummary(
        id=agent.id, project_id=agent.project_id, name=agent.name, status=status,
        last_heartbeat_at=heartbeat, git_remote=agent.git_remote,
        repository_path_hint=agent.repository_path_hint,
        created_at=as_utc(agent.created_at), updated_at=as_utc(agent.updated_at),
    )


def _summary(session: Session, project: Project, active_tasks: int, agents: int) -> ProjectSummary:
    now = datetime.now(timezone.utc)
    return ProjectSummary(
        id=project.id, name=project.name, description=project.description,
        active_task_count=active_tasks,
        agents=[_agent_summary(agent, now) for agent in AgentRepository(session).for_project(
            project.id, limit=max(agents, 1),
        )],
        telegram_chat_id=project.telegram_chat_id,
        created_at=as_utc(project.created_at), updated_at=as_utc(project.updated_at),
    )


def list_projects(session: Session, offset: int = 0, limit: int = 50) -> list[ProjectSummary]:
    return [_summary(session, *row) for row in ProjectRepository(session).with_counts(
        offset=offset, limit=limit,
    )]


def project_card(session: Session, project_id: UUID) -> ProjectCard:
    rows = ProjectRepository(session).with_counts(project_id)
    if not rows:
        raise not_found()
    project, active_tasks, agents = rows[0]
    expires = ProjectInitTokenRepository(session).latest_unused_expiry(
        project_id, datetime.now(timezone.utc),
    )
    summary = _summary(session, project, active_tasks, agents).model_dump()
    summary["init_code_expires_at"] = as_utc(expires) if expires else None
    return ProjectCard(**summary)


def create_project(session: Session, body: ProjectCreate) -> ProjectCard:
    project = ProjectRepository(session).create(**body.model_dump())
    response = project_card(session, project.id)
    session.commit()
    return response


def create_init_token(session: Session, project_id: UUID) -> InitTokenResponse:
    code, expires_at = issue_init_token(session, project_id)
    response = InitTokenResponse(code=code, expires_at=expires_at)
    session.commit()
    return response


def list_agents(session: Session, project_id: UUID, offset: int = 0,
                limit: int = 50) -> list[AgentSummary]:
    get_project(session, project_id)
    results = []
    for agent in AgentRepository(session).for_project(project_id, offset, limit):
        results.append(_agent_summary(agent, datetime.now(timezone.utc)))
    return results
