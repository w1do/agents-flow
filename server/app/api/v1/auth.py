from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import ACCESS_TOKEN_TTL
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.auth import login
from app.api.rate_limit import LoginLimit, login_rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login_admin(body: LoginRequest, session: Annotated[Session, Depends(get_db)],
                limit: Annotated[LoginLimit, Depends(login_rate_limit)]):
    token = login(session, body.email, body.password.get_secret_value())
    limit.reset_after_success()
    return TokenResponse(access_token=token, expires_in=int(ACCESS_TOKEN_TTL.total_seconds()))
