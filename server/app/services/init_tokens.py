from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import forbidden, not_found, unauthorized
from app.core.security import hash_token
from app.core.time import as_utc
from app.models.agent import Agent
from app.repositories.agent import AgentRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_init_token import ProjectInitTokenRepository
from app.services.agent_auth import generate_agent_token

INIT_TOKEN_TTL = timedelta(minutes=10)


def issue_init_token(session: Session, project_id: UUID) -> tuple[str, datetime]:
    if ProjectRepository(session).get(project_id) is None:
        raise not_found()
    code = token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + INIT_TOKEN_TTL
    ProjectInitTokenRepository(session).create(
        project_id=project_id, token_hash=hash_token(code), expires_at=expires_at,
    )
    return code, expires_at


def consume_init_token(
    session: Session, code: str, project_id: UUID, *, agent_name: str | None = None,
    agent_token_hash: str | None = None, repository_path_hint: str = "", git_remote: str = "",
) -> Agent:
    tokens, agents = ProjectInitTokenRepository(session), AgentRepository(session)
    name = agent_name if agent_name is not None else f"agent-{uuid4()}"
    try:
        with session.begin_nested():
            token = tokens.by_hash(hash_token(code))
            now = datetime.now(timezone.utc)
            if token is None or token.used_at is not None or as_utc(token.expires_at) <= now:
                raise unauthorized()
            if token.project_id != project_id:
                raise forbidden()
            if agents.by_name(project_id, name) is not None:
                raise HTTPException(409, "Conflict")
            if not tokens.mark_used(token.id, now):
                raise unauthorized()
            return agents.create(
                project_id=project_id, name=name, status="offline",
                agent_token_hash=agent_token_hash or generate_agent_token()[1],
                repository_path_hint=repository_path_hint, git_remote=git_remote,
            )
    except IntegrityError:
        if agents.by_name(project_id, name) is not None:
            raise HTTPException(409, "Conflict") from None
        raise
