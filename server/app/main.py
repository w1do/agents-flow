import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.routing import Route

from app.api.v1.router import router
from app.core.config import get_settings
from app.mcp.tools import create_server
from app.mcp.transport import AgentTokenMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.body_limit import BodyLimitMiddleware
from app.schemas.health import HealthResponse

@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    application.state.settings = settings
    from app.services.lease_expiry import monitor, stop_monitor

    expiry_task = asyncio.create_task(monitor())
    transport = application.state.mcp_transport
    # SDK session managers are single-use; build one for each app lifespan.
    transport.app = create_server().streamable_http_app(
        stateless_http=True, json_response=True, host="0.0.0.0",
    )
    try:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(transport.app.router.lifespan_context(transport.app))
            if hasattr(application.state, "telegram"):
                from app.core.db import SessionLocal
                from app.services.notification_events import running

                await stack.enter_async_context(running(application.state.telegram, SessionLocal.kw["bind"]))
            yield
    finally:
        await stop_monitor(expiry_task)


def create_app(*, web_dist: Path | None = None) -> FastAPI:
    application = FastAPI(title="Agents Flow", version="0.1.0", lifespan=lifespan)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(BodyLimitMiddleware)

    application.include_router(router, prefix="/api/v1")
    settings = get_settings()
    if settings.telegram_bot_token.get_secret_value():
        from app.api.v1.telegram import router as telegram_router
        from app.integrations.telegram.runtime import Runtime

        application.state.telegram = Runtime(settings)
        application.include_router(telegram_router, prefix="/api/v1")

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

    dist = (web_dist if web_dist is not None else Path(__file__).resolve().parents[1] / "web" / "dist").resolve()
    if (dist / "index.html").is_file():
        default = application.router.default

        def accepts_html(scope):
            headers = dict(scope.get("headers", []))
            accepted = headers.get(b"accept", b"").decode().lower()
            for item in accepted.split(","):
                media_type, *params = item.split(";")
                quality = next((part.strip()[2:] for part in params if part.strip().startswith("q=")), "1")
                try:
                    if media_type.strip() == "text/html" and float(quality) > 0:
                        return True
                except ValueError:
                    continue
            return False

        async def panel(scope, receive, send):
            # Only unmatched requests reach this handler. API routes keep their
            # original execution context, cancellation and streaming behavior.
            path = scope.get("path", "").lstrip("/")
            parts = path.rstrip("/").split("/")
            reserved = parts[0] in {"api", "mcp", "healthz", "docs", "redoc", "openapi.json"}
            if scope["type"] == "http" and scope["method"] == "GET" and not reserved:
                candidate = (dist / path).resolve()
                is_screen = parts in [[""], ["login"], ["projects"], ["skills"]] or (
                    len(parts) == 2 and parts[0] in {"projects", "tasks"} and not Path(parts[1]).suffix
                )
                response = None
                if candidate.is_relative_to(dist):
                    if candidate.is_file():
                        headers = {"Cache-Control": "no-cache"} if path == "index.html" else None
                        response = FileResponse(candidate, headers=headers)
                    elif is_screen and accepts_html(scope):
                        response = FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
                if response is not None:
                    await response(scope, receive, send)
                    return
            await default(scope, receive, send)

        application.router.default = panel

    return application


app = create_app()
