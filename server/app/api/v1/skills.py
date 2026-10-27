from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Database
from app.api.flow_deps import Write, flow_admin
from app.schemas.skills import SkillCreate, SkillPatch, SkillResponse
from app.services import skills

router = APIRouter(prefix="/skills", tags=["skills"], dependencies=[Depends(flow_admin)])


@router.get("", response_model=list[SkillResponse])
def listing(session: Database, category_id: UUID | None = None, is_active: bool | None = None,
            offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    return skills.list_skills(session, category_id, is_active, offset, limit)


@router.post("", response_model=SkillResponse, status_code=201)
def create(body: SkillCreate, session: Database, write: Write):
    return write.run(body, lambda: skills.skill_save(session, body), status=201)


@router.get("/{skill_id}", response_model=SkillResponse)
def get(skill_id: UUID, session: Database):
    return skills.skill_response(session, skills.get_skill(session, skill_id))


@router.patch("/{skill_id}", response_model=SkillResponse)
def patch(skill_id: UUID, body: SkillPatch, session: Database, write: Write):
    return write.run(body, lambda: skills.skill_save(session, body, skill_id))


@router.post("/{skill_id}/archive", response_model=SkillResponse)
def archive(skill_id: UUID, session: Database, write: Write):
    return write.run({}, lambda: skills.archive(session, skill_id))
