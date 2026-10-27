import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.router import router
from app.core.config import get_settings
from app.schemas.health import HealthResponse
from app.services.auth import ensure_initial_admin


@asynccontextmanager
async def lifespan(application: FastAPI):
    from app.core.db import SessionLocal

    settings = get_settings()
    application.state.settings = settings
    with SessionLocal.begin() as session:
        ensure_initial_admin(session, settings)
    from app.services.lease_expiry import monitor, stop_monitor

    expiry_task = asyncio.create_task(monitor())
    try:
        yield
    finally:
        await stop_monitor(expiry_task)


def create_app() -> FastAPI:
    application = FastAPI(title="Agents Flow", version="0.1.0", lifespan=lifespan)
    application.include_router(router, prefix="/api/v1")

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request, exception: RequestValidationError):
        # Validation errors must not echo credentials or the original request body.
        errors = [{key: error[key] for key in ("loc", "msg", "type")}
                  for error in exception.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @application.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        return HealthResponse()

    return application


app = create_app()
