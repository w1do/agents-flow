"""Bound task report bodies before JSON parsing, including chunked requests."""
import re

from starlette.responses import JSONResponse

from app.middleware.json_depth import excessive_depth

MAX_BODY_BYTES = 512 * 1024


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        root = scope.get("root_path", "").rstrip("/")
        if root and path.startswith(root + "/"):
            path = path[len(root):]
        if scope["type"] != "http" or not re.fullmatch(
            r"/api/v1/tasks/[^/]+/(plan|events|result|publication-result|fail)", path
        ):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = MAX_BODY_BYTES + 1
        chunks, size = [], 0
        if 0 <= declared <= MAX_BODY_BYTES:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    break
                chunks.append(chunk)
                if not message.get("more_body", False):
                    body = b"".join(chunks)
                    if excessive_depth(body):
                        response = JSONResponse(status_code=422, content={"detail": "Request nesting exceeds limit"})
                        return await response(scope, receive, send)

                    async def replay():
                        nonlocal body
                        if body is not None:
                            value, body = body, None
                            return {"type": "http.request", "body": value, "more_body": False}
                        return await receive()

                    return await self.app(scope, replay, send)
        response = JSONResponse(status_code=422, content={"detail": "Request body exceeds 512 KiB"})
        await response(scope, receive, send)
