"""One transactional service invocation with compact, non-reflective errors."""
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.repositories.agent import AgentRepository
from app.schemas.mcp import TOOL_SCHEMAS
from app.services import mcp_audit, mcp_tools
from app.services.lease_expiry import expire_due
from app.services.skill_content import sanitize

MESSAGES = {
    401: "Unauthorized", 403: "Forbidden", 404: "Not found",
    409: "Conflict: check lease and task state", 422: "Invalid arguments",
    500: "Internal error",
}


def error(code):
    return {"error": {"code": code, "message": MESSAGES.get(code, "Request failed")}}


def invoke(agent_id, name, arguments):
    from app.core.db import SessionLocal

    try:
        with SessionLocal() as session:
            agent = AgentRepository(session).get(agent_id)
            if agent is None:
                return error(401)
            expire_due(session, agent.project_id)
            code = 200
            try:
                schema = TOOL_SCHEMAS.get(name)
                if schema is None:
                    raise HTTPException(404)
                body = schema.model_validate(arguments)
                result = sanitize(jsonable_encoder(mcp_tools.execute(session, agent, name, body)))
            except ValidationError:
                code = 422
            except HTTPException as exception:
                code = exception.status_code
            except Exception:
                code = 500
            if code != 200:
                session.rollback()
            mcp_audit.record(session, agent, name, arguments, code)
            session.commit()
            return result if code == 200 else error(code)
    except Exception:
        return error(500)
