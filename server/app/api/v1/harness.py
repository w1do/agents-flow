from fastapi import APIRouter

from app.api.deps import Database
from app.schemas.harness import HarnessInitRequest, HarnessInitResponse
from app.services.harness import initialize_harness

router = APIRouter(prefix="/harness", tags=["harness"])


@router.post("/init", response_model=HarnessInitResponse, status_code=201)
def init_harness(body: HarnessInitRequest, session: Database):
    return initialize_harness(session, body)
