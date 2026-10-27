from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Database
from app.api.flow_deps import Write, flow_admin
from app.schemas.skills import CategoryCreate, CategoryPatch, CategoryResponse
from app.services import skills

router = APIRouter(prefix="/skill-categories", tags=["skills"], dependencies=[Depends(flow_admin)])


@router.get("", response_model=list[CategoryResponse])
def listing(session: Database, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    return skills.list_categories(session, offset, limit)


@router.post("", response_model=CategoryResponse, status_code=201)
def create(body: CategoryCreate, session: Database, write: Write):
    return write.run(body, lambda: skills.category_save(session, body), status=201)


@router.patch("/{category_id}", response_model=CategoryResponse)
def patch(category_id: UUID, body: CategoryPatch, session: Database, write: Write):
    return write.run(body, lambda: skills.category_save(session, body, category_id))
