from typing import Annotated

import re

from fastapi import Depends, Header, HTTPException, Request

from app.api.deps import Credentials, Database
from app.core.errors import forbidden, not_found, unauthorized
from app.models import Agent, User
from app.services.agent_auth import authenticate_agent
from app.services.auth import authenticate_admin
from app.services.idempotency import execute
from app.services.lease_expiry import expire_due
from app.services.skill_content import contains_secret


def principal(credentials: Credentials, session: Database):
    if credentials is None:
        raise unauthorized()
    token = credentials.credentials
    actor = authenticate_agent(token, session) or authenticate_admin(session, token)
    if actor is None:
        raise unauthorized()
    return actor


Actor = Annotated[User | Agent, Depends(principal)]


def flow_admin(actor: Actor, session: Database):
    if not isinstance(actor, User):
        raise forbidden()
    expire_due(session)
    return actor


def flow_agent(actor: Actor, session: Database):
    if not isinstance(actor, Agent):
        raise forbidden()
    expire_due(session, actor.project_id)
    return actor


Admin = Annotated[User, Depends(flow_admin)]
AgentActor = Annotated[Agent, Depends(flow_agent)]


def own_agent(actor, agent_id):
    if actor.id != agent_id:
        raise not_found()


class Mutation:
    def __init__(self, session, scope, key):
        self.session, self.scope, self.key = session, scope, key

    def run(self, body, operation, status=200, empty_status=None):
        return execute(self.session, self.scope, self.key, body, operation, status, empty_status)


def mutation(request: Request, session: Database, actor: Actor,
             key: Annotated[str, Header(alias="Idempotency-Key")]):
    key = key.strip()
    if not 1 <= len(key) <= 200 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key) or contains_secret(key):
        raise HTTPException(422, "Invalid Idempotency-Key")
    scope = f"{actor.__tablename__}:{actor.id}:{request.method}:{request.url.path}"
    return Mutation(session, scope, key)


Write = Annotated[Mutation, Depends(mutation)]
