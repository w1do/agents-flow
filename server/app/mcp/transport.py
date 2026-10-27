"""Authenticate each HTTP request before it reaches the MCP SDK."""
import json

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.services.agent_auth import authenticate_agent
from app.services.mcp_calls import error


def _safe_rpc(value):
    if isinstance(value, list):
        return [_safe_rpc(item) for item in value]
    if isinstance(value, dict) and value.get("jsonrpc") == "2.0":
        if isinstance(value.get("error"), dict):
            value["error"]["message"] = "MCP request failed"
            if "data" in value["error"]:
                value["error"]["data"] = "MCP request failed"
            return value
    return value


def _safe_json(data):
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return data
    messages = value if isinstance(value, list) else [value]
    if not any(isinstance(item, dict) and item.get("jsonrpc") == "2.0"
               and isinstance(item.get("error"), dict) for item in messages):
        return data
    return json.dumps(_safe_rpc(value), separators=(",", ":"), ensure_ascii=False).encode()


def _safe_sse(event):
    lines = event.splitlines(keepends=True)
    result = []
    for line in lines:
        content = line.rstrip(b"\r\n")
        if content.startswith(b"data:"):
            prefix, payload = content[:5], content[5:].lstrip()
            content = prefix + b" " + _safe_json(payload) if payload else content
            ending = line[len(line.rstrip(b"\r\n")):]
            line = content + ending
        result.append(line)
    return b"".join(result)


def _next_sse_event(pending):
    separators = (b"\r\n\r\n", b"\n\n")
    matches = [(pending.find(separator), separator) for separator in separators]
    matches = [(index, separator) for index, separator in matches if index >= 0]
    if not matches:
        return None
    index, separator = min(matches, key=lambda match: match[0])
    end = index + len(separator)
    event = bytes(pending[:end])
    del pending[:end]
    return event


def agent_identity(token):
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        agent = authenticate_agent(token, session)
        return agent.id if agent else None


class AgentTokenMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "").removeprefix(scope.get("root_path", ""))
        if scope["type"] != "http" or path not in {"/mcp", "/mcp/"}:
            return await self.app(scope, receive, send)
        request = Request(scope)
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        agent_id = None
        if scheme.lower() == "bearer" and token:
            try:
                agent_id = await run_in_threadpool(agent_identity, token)
            except Exception:
                return await JSONResponse(error(500), status_code=500)(scope, receive, send)
        if agent_id is None:
            response = JSONResponse({"error": {"code": 401, "message": "Unauthorized"}},
                                    status_code=401, headers={"WWW-Authenticate": "Bearer"})
            return await response(scope, receive, send)
        scope.setdefault("state", {})["mcp_agent_id"] = agent_id
        rejected = False
        response_status = None
        content_type = b""
        pending = bytearray()

        async def safe_send(message):
            nonlocal rejected, response_status, content_type
            if message["type"] == "http.response.start":
                response_status = message["status"]
                content_type = next((value for key, value in message["headers"]
                                     if key.lower() == b"content-type"), b"").lower()
            if message["type"] == "http.response.start" and message["status"] >= 400:
                rejected = True
                # The SDK's wire-level Pydantic errors can echo raw input.
                headers = {key.decode(): value.decode() for key, value in message["headers"]
                           if key.lower() not in {b"content-length", b"content-type"}}
                response = JSONResponse(error(message["status"]), status_code=message["status"],
                                        headers=headers)
                await response(scope, receive, send)
            elif not rejected:
                if (message["type"] == "http.response.start" and response_status == 200
                        and content_type.startswith(b"application/json")):
                    headers = [(key, value) for key, value in message["headers"]
                               if key.lower() != b"content-length"]
                    await send({**message, "headers": headers})
                elif (message["type"] == "http.response.start" and response_status == 200
                      and content_type.startswith(b"text/event-stream")):
                    headers = [(key, value) for key, value in message["headers"]
                               if key.lower() != b"content-length"]
                    await send({**message, "headers": headers})
                elif message["type"] == "http.response.body" and response_status == 200:
                    body = message.get("body", b"")
                    if content_type.startswith(b"application/json"):
                        pending.extend(body)
                        if not message.get("more_body", False):
                            await send({**message, "body": _safe_json(bytes(pending))})
                    elif content_type.startswith(b"text/event-stream"):
                        pending.extend(body)
                        event = _next_sse_event(pending)
                        while event is not None:
                            await send({**message, "body": _safe_sse(event),
                                        "more_body": True})
                            event = _next_sse_event(pending)
                        if not message.get("more_body", False):
                            if pending:
                                await send({**message, "body": _safe_sse(bytes(pending))})
                            else:
                                await send({**message, "body": b""})
                    else:
                        await send(message)
                else:
                    await send(message)

        await self.app(scope, receive, safe_send)
