from secrets import token_urlsafe

from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.models.agent import Agent
from app.repositories.agent import AgentRepository


def generate_agent_token() -> tuple[str, str]:
    token = token_urlsafe(32)
    return token, hash_token(token)


def authenticate_agent(token: str, session: Session | None = None) -> Agent | None:
    if not token:
        return None
    if session is None:
        from app.core.db import SessionLocal

        with SessionLocal() as database:
            return authenticate_agent(token, database)
    return AgentRepository(session).by_token_hash(hash_token(token))
