from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import Database
from app.api.flow_deps import AgentActor, Write, flow_admin, own_agent
from app.schemas.skills import AgentSkillsReplace, SkillResponse
from app.services import skills

router = APIRouter(prefix="/agents", tags=["skills"])


@router.get("/{agent_id}/skills", response_model=list[SkillResponse], dependencies=[Depends(flow_admin)])
def get(agent_id: UUID, session: Database):
    return skills.assigned(session, agent_id)


@router.put("/{agent_id}/skills", response_model=list[SkillResponse], dependencies=[Depends(flow_admin)])
def replace(agent_id: UUID, body: AgentSkillsReplace, session: Database, write: Write):
    return write.run(body, lambda: skills.replace(session, agent_id, body))


@router.get("/{agent_id}/skills/sync")
def sync(agent_id: UUID, actor: AgentActor, session: Database):
    own_agent(actor, agent_id)
    return skills.sync(session, agent_id)
