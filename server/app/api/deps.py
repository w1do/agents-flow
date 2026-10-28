from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, object_session

from app.core.db import get_db
from app.core.errors import not_found, unauthorized
from app.models import Agent, User
from app.services.agent_auth import authenticate_agent
from app.services.auth import authenticate_admin
from app.services import projects

bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
Database = Annotated[Session, Depends(get_db)]


def require_admin(credentials: Credentials, session: Database, request: Request,
                  session_cookie: Annotated[str | None, Cookie(alias="session")] = None,
                  requested_with: Annotated[str | None, Header(alias="X-Requested-With")] = None) -> User:
    token = credentials.credentials if credentials else session_cookie
    if credentials is None and session_cookie and request.method not in {"GET", "HEAD", "OPTIONS"} \
            and requested_with != "XMLHttpRequest":
        raise HTTPException(403, "CSRF validation failed")
    user = authenticate_admin(session, token) if token else None
    if user is None:
        raise unauthorized()
    return user


def require_agent(credentials: Credentials, session: Database) -> Agent:
    agent = authenticate_agent(credentials.credentials, session) if credentials else None
    if agent is None:
        raise unauthorized()
    return agent


def ensure_project_access(agent: Agent | None, project_id: UUID | None) -> None:
    if agent is None or project_id is None:
        raise not_found()
    session = object_session(agent)
    if session is None or projects.get_agent_for_project(session, agent.id, project_id) is None:
        raise not_found()


def ensure_agent_access(agent: Agent, target: Agent | None) -> None:
    session = object_session(agent)
    authorized = projects.get_agent_for_project(session, target.id, agent.project_id) if session and target else None
    if target is None or authorized is None or agent.id != target.id:
        raise not_found()
