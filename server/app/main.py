import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.routing import Route

from app.api.v1.router import router
from app.core.config import get_settings
from app.mcp.tools import create_server
from app.mcp.transport import AgentTokenMiddleware
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
    transport = application.state.mcp_transport
    # SDK session managers are single-use; build one for each app lifespan.
    transport.app = create_server().streamable_http_app(
        stateless_http=True, json_response=True, host="0.0.0.0",
    )
    try:
        async with transport.app.router.lifespan_context(transport.app):
            yield
    finally:
        await stop_monitor(expiry_task)


def create_app() -> FastAPI:
    application = FastAPI(title="Agents Flow", version="0.1.0", lifespan=lifespan)
    application.include_router(router, prefix="/api/v1")

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request, exception: RequestValidationError):
        # Validation errors must not echo credentials or the original request body.
        errors = [{key: error[key] for key in ("msg", "type")}
                  for error in exception.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @application.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        return HealthResponse()

    # Route the SDK ASGI app at the exact endpoint without shadowing other routes.
    transport = AgentTokenMiddleware(None)
    application.state.mcp_transport = transport
    application.router.routes.append(Route("/mcp", endpoint=transport))
    return application


app = create_app()
