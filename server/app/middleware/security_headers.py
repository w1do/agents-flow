import asyncio
import logging

from fastapi.responses import JSONResponse

from app.services.skill_content import redact

logger = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def exception_text(error):
    """Flatten groups without ever letting exception formatting escape."""
    try:
        if isinstance(error, BaseExceptionGroup):
            return "; ".join(exception_text(child) for child in error.exceptions)
        return redact(str(error))
    except BaseException:
        return "Exception text unavailable"


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False
        interruption = RuntimeError("Response stream interrupted")

        async def send_with_headers(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                headers.extend((key.lower().encode(), value.encode()) for key, value in SECURITY_HEADERS.items()
                               if key.lower().encode() not in existing)
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except BaseException as error:
            if not isinstance(error, (Exception, BaseExceptionGroup)):
                interruption = error
            else:
                try:
                    logger.error("Unhandled request exception: %s", exception_text(error))
                except BaseException as logging_error:
                    if not isinstance(logging_error, (Exception, BaseExceptionGroup)):
                        interruption = logging_error
                else:
                    if not response_started:
                        response = JSONResponse({"detail": "Internal Server Error"}, status_code=500)
                        try:
                            await response(scope, receive, send_with_headers)
                        except BaseException:
                            pass  # A failed fallback must not carry the original context.
                        else:
                            return
        else:
            return

        # Uvicorn closes a started response on error. Raise outside the handler
        # so neither __context__ nor traceback logging can expose the original.
        if isinstance(interruption, asyncio.CancelledError):
            interruption = asyncio.CancelledError("Request cancelled")
        elif isinstance(interruption, (SystemExit, KeyboardInterrupt, GeneratorExit)):
            interruption = type(interruption)()
        interruption.__cause__ = interruption.__context__ = None
        raise interruption from None
