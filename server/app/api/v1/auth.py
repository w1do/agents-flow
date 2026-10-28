from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import ACCESS_TOKEN_TTL
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.auth import login
from app.api.deps import require_admin
from app.models import User
from app.api.rate_limit import LoginLimit, login_rate_limit
from app.api.proxy import request_is_secure
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", status_code=204)
def login_admin(body: LoginRequest, session: Annotated[Session, Depends(get_db)],
                limit: Annotated[LoginLimit, Depends(login_rate_limit)],
                request: Request, response: Response):
    token = login(session, body.email, body.password.get_secret_value())
    limit.reset_after_success()
    secure = request_is_secure(request, get_settings().trusted_proxy_ips)
    response.set_cookie("session", token, httponly=True, samesite="strict", secure=secure,
                        path="/", max_age=int(ACCESS_TOKEN_TTL.total_seconds()))
    response.status_code = 204
    return response


@router.post("/token", response_model=TokenResponse)
def issue_token(body: LoginRequest, session: Annotated[Session, Depends(get_db)],
                limit: Annotated[LoginLimit, Depends(login_rate_limit)]):
    """Issue a bearer token for CLI, API clients, and test harnesses.

    Browser clients should use /login, which sets an HttpOnly session cookie.
    """
    token = login(session, body.email, body.password.get_secret_value())
    limit.reset_after_success()
    return TokenResponse(access_token=token, expires_in=int(ACCESS_TOKEN_TTL.total_seconds()))


@router.get("/session", status_code=204)
def check_session(_user: Annotated[User, Depends(require_admin)]):
    return Response(status_code=204)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response,
           requested_with: Annotated[str | None, Header(alias="X-Requested-With")] = None):
    if requested_with != "XMLHttpRequest":
        raise HTTPException(403, "CSRF validation failed")
    secure = request_is_secure(request, get_settings().trusted_proxy_ips)
    response.delete_cookie("session", path="/", secure=secure,
                           httponly=True, samesite="strict")
    response.status_code = 204
    return response
