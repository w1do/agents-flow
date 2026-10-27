from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Database, require_admin
from app.schemas.projects import (
    AgentSummary, InitTokenResponse, ProjectCard, ProjectCreate, ProjectSummary,
)
from app.services import projects

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[ProjectSummary])
def list_projects(session: Database, offset: int = Query(0, ge=0),
                  limit: int = Query(50, ge=1, le=200)):
    return projects.list_projects(session, offset, limit)


@router.post("", response_model=ProjectCard, status_code=201)
def create_project(body: ProjectCreate, session: Database):
    return projects.create_project(session, body)


@router.get("/{project_id}", response_model=ProjectCard)
def get_project(project_id: UUID, session: Database):
    return projects.project_card(session, project_id)


@router.get("/{project_id}/agents", response_model=list[AgentSummary])
def list_project_agents(project_id: UUID, session: Database, offset: int = Query(0, ge=0),
                        limit: int = Query(50, ge=1, le=200)):
    return projects.list_agents(session, project_id, offset, limit)


@router.post("/{project_id}/init-tokens", response_model=InitTokenResponse, status_code=201)
def create_init_token(project_id: UUID, session: Database):
    return projects.create_init_token(session, project_id)
