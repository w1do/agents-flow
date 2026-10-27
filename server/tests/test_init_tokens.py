from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Agent, ProjectInitToken
from app.repositories.project import ProjectRepository
from app.services.init_tokens import consume_init_token, issue_init_token


def test_issue_and_consume(session, project):
    before = datetime.now(timezone.utc)
    code, expires = issue_init_token(session, project.id)
    assert before + timedelta(minutes=10) <= expires <= datetime.now(timezone.utc) + timedelta(minutes=10)
    stored = session.scalar(select(ProjectInitToken))
    assert stored.token_hash == sha256(code.encode()).hexdigest()
    assert stored.token_hash != code
    assert stored.used_at is None
    agent = consume_init_token(session, code, project.id)
    assert isinstance(agent, Agent)
    assert agent.project_id == project.id
    assert agent.status == "offline"
    assert stored.used_at is not None
    assert session.scalar(select(func.count()).select_from(Agent)) == 1


def test_repeated_code(session, project):
    code, _ = issue_init_token(session, project.id)
    consume_init_token(session, code, project.id)
    with pytest.raises(HTTPException) as error:
        consume_init_token(session, code, project.id)
    assert error.value.status_code == 401
    assert error.value.detail == "Unauthorized"
    assert session.scalar(select(func.count()).select_from(Agent)) == 1


def test_expired_code(session, project):
    code, _ = issue_init_token(session, project.id)
    stored = session.scalar(select(ProjectInitToken))
    stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.flush()
    with pytest.raises(HTTPException) as error:
        consume_init_token(session, code, project.id)
    assert error.value.status_code == 401
    assert stored.used_at is None
    assert session.scalar(select(func.count()).select_from(Agent)) == 0


def test_foreign_project(session, project):
    foreign = ProjectRepository(session).create(name="Foreign")
    code, _ = issue_init_token(session, project.id)
    with pytest.raises(HTTPException) as error:
        consume_init_token(session, code, foreign.id)
    assert error.value.status_code == 403
    assert error.value.detail == "Forbidden"
    assert consume_init_token(session, code, project.id).project_id == project.id


def test_unknown_code(session, project):
    with pytest.raises(HTTPException) as error:
        consume_init_token(session, "unknown", project.id)
    assert error.value.status_code == 401


def test_conditional_consumption_updates_once(session, project):
    from app.repositories.project_init_token import ProjectInitTokenRepository

    issue_init_token(session, project.id)
    token = session.scalar(select(ProjectInitToken))
    tokens = ProjectInitTokenRepository(session)
    assert tokens.mark_used(token.id, datetime.now(timezone.utc))
    assert not tokens.mark_used(token.id, datetime.now(timezone.utc))
