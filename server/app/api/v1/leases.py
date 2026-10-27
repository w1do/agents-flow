from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Database
from app.api.flow_deps import AgentActor, Write, own_agent
from app.api.agent_claim_limit import check_claim_limit
from app.schemas.leases import ClaimRequest, ClaimResponse, HeartbeatRequest, HeartbeatResponse
from app.services import leases

router = APIRouter(prefix="/agents", tags=["leases"])


@router.post("/{agent_id}/leases/claim", response_model=ClaimResponse,
             responses={204: {"description": "Нет доступных задач"}})
def claim(agent_id: UUID, body: ClaimRequest, actor: AgentActor, session: Database, write: Write):
    own_agent(actor, agent_id)
    check_claim_limit(agent_id)
    return write.run(body, lambda: leases.claim(session, actor), empty_status=204)


@router.post("/{agent_id}/heartbeat", response_model=HeartbeatResponse)
def heartbeat(agent_id: UUID, body: HeartbeatRequest, actor: AgentActor, session: Database, write: Write):
    own_agent(actor, agent_id)
    return write.run(body, lambda: leases.heartbeat(session, actor, body))
